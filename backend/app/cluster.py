"""Build the real cluster view (nodes, pods, GPU) from the live k3s cluster.

This file answers "what's actually running on the box right now?" and packages it into the
`Cluster` object the console draws as the data-center floor. It also seeds the list of
"assets" (the things worth protecting: the weights, the training job, the notebook, the node).

Everything here reads the cluster through the admin client. No synthetic data:
pods, cordon status, and GPU numbers all come from the API server and from
nvidia-smi run inside the platform telemetry pod.

Concepts (new here?):
  * nvidia-smi is NVIDIA's command-line tool that reports a GPU's utilization, memory and
    temperature. We run it inside a pod that has the GPU attached and parse its CSV output.
  * "Cordon" is a Kubernetes state meaning "don't schedule new pods on this node" (used by
    the defender to protect a node); you'll see cordon status surfaced to the UI here.
  * The "owner" label (owner=law-firm) is the trust signal: every legitimate workload carries
    it, so a pod WITHOUT it is, by definition, something the attacker created.
"""
from __future__ import annotations

from . import config
from .k8s import ApiException, admin_core, admin_net, exec_in_pod, first_pod_name, admin
from .models import Asset, Cluster, ClusterNode, Gpu, Pod, now_iso

# Namespaces whose pods appear on the floor (the victim fleet + platform).
VISIBLE_NS = (config.LAWFIRM_NS, config.PLATFORM_NS)

NVIDIA_SMI = [
    "nvidia-smi",
    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
    "--format=csv,noheader,nounits",
]


# --- Pod classification helpers -------------------------------------------
# These derive the fields the UI and the detector care about from a raw k8s pod.
def _pod_uses_gpu(pod) -> bool:
    for c in pod.spec.containers or []:
        res = c.resources
        for bag in (res.limits or {}, res.requests or {}):
            if "nvidia.com/gpu" in bag:
                return True
    return False


def _pod_mounts_weights(pod) -> bool:
    for v in pod.spec.volumes or []:
        if v.persistent_volume_claim and v.persistent_volume_claim.claim_name == config.MODEL_WEIGHTS_PVC:
            return True
    return False


def _owner_of(pod) -> str:
    # The owner label is the core trust signal: every legitimate workload carries
    # owner=law-firm or owner=platform. A pod with no (or an unknown) owner label is
    # what the detector flags as an intruder — attacker pods never set it.
    label = (pod.metadata.labels or {}).get("owner")
    if label == "law-firm":
        return "law-firm"
    if label == "platform":
        return "platform"
    return "unknown"


def _phase(pod) -> str:
    if pod.metadata.deletion_timestamp is not None:
        return "Terminating"
    phase = pod.status.phase if pod.status else "Pending"
    return phase if phase in ("Running", "Pending", "Succeeded", "Failed") else "Pending"


def _health_for_phase(phase: str) -> str:
    return {
        "Running": "healthy",
        "Pending": "degraded",
        "Succeeded": "healthy",
        "Failed": "critical",
        "Terminating": "degraded",
    }.get(phase, "degraded")


def quarantine_np_names() -> set[str]:
    """NetworkPolicies named quarantine-* currently in lawfirm."""
    try:
        nps = admin_net().list_namespaced_network_policy(config.LAWFIRM_NS)
    except ApiException:
        return set()
    return {np.metadata.name for np in nps.items if np.metadata.name.startswith("quarantine-")}


def list_pods() -> list[Pod]:
    core = admin_core()
    quarantined = quarantine_np_names()
    out: list[Pod] = []
    for ns in VISIBLE_NS:
        try:
            pods = core.list_namespaced_pod(ns)
        except ApiException:
            continue
        for p in pods.items:
            name = p.metadata.name
            phase = _phase(p)
            out.append(
                Pod(
                    name=name,
                    namespace=ns,
                    node=p.spec.node_name or "",
                    phase=phase,
                    owner=_owner_of(p),
                    usesGpu=_pod_uses_gpu(p),
                    health=_health_for_phase(phase),
                    quarantined=f"quarantine-{name}" in quarantined,
                )
            )
    return out


# --- Live GPU telemetry ----------------------------------------------------
def read_gpus() -> tuple[list[Gpu], float]:
    """Exec nvidia-smi in the telemetry pod. Returns (gpus, total utilization).

    The backend runs off-cluster, so it can't see the GPU directly; instead it
    execs nvidia-smi inside the platform telemetry pod (which has GPU access) and
    parses the CSV. `total` is the max utilization across GPUs — the miner spike
    the detector watches for. Real numbers only, never synthetic."""
    pod = first_pod_name(admin(), config.PLATFORM_NS, config.TELEMETRY_LABEL)
    if not pod:
        return [], 0.0
    raw = exec_in_pod(admin(), config.PLATFORM_NS, pod, NVIDIA_SMI)
    gpus: list[Gpu] = []
    for line in raw.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            idx, model, util, mem_used, mem_total, temp = parts[:6]
            gpus.append(
                Gpu(
                    index=int(idx),
                    model=model,
                    utilization=float(util),
                    memUsedGiB=round(float(mem_used) / 1024, 2),
                    memTotalGiB=round(float(mem_total) / 1024, 2),
                    tempC=float(temp),
                )
            )
        except ValueError:
            continue
    total = max((g.utilization for g in gpus), default=0.0)
    return gpus, total


def build_node(gpus: list[Gpu]) -> ClusterNode:
    core = admin_core()
    nodes = core.list_node().items
    node = nodes[0] if nodes else None
    if node is None:
        return ClusterNode(name="unknown", role="gpu-worker", health="unreachable",
                           cordoned=False, gpus=gpus, cpuPct=0.0)
    cap = node.status.capacity or {}
    role = "gpu-worker" if "nvidia.com/gpu" in cap else "control-plane"
    cordoned = bool(node.spec.unschedulable)
    ready = any(c.type == "Ready" and c.status == "True" for c in (node.status.conditions or []))
    return ClusterNode(
        name=node.metadata.name,
        role=role,
        health="healthy" if ready else "unreachable",
        cordoned=cordoned,
        gpus=gpus,
        cpuPct=0.0,
    )


def build_cluster(gpu_history: list[float], gpus: list[Gpu] | None = None) -> Cluster:
    if gpus is None:
        gpus, _total = read_gpus()
    node = build_node(gpus)
    return Cluster(name="halloran-vance-gpu", nodes=[node], pods=list_pods(), gpuHistory=gpu_history)


# --- Protected assets (scope) ----------------------------------------------
def seed_assets() -> list[Asset]:
    """The protected assets, all clean at the start. Refs point at live objects.

    Returns the list; it does NOT write the store. main.py's startup seeds the
    store from this, and anything resetting scope must upsert these back in."""
    ts = now_iso()
    node_name = ""
    try:
        nodes = admin_core().list_node().items
        node_name = nodes[0].metadata.name if nodes else ""
    except ApiException:
        pass
    notebook = first_pod_name(admin(), config.LAWFIRM_NS, config.NOTEBOOK_LABEL) or "notebook"
    training = first_pod_name(admin(), config.LAWFIRM_NS, "app=training") or "training"
    return [
        Asset(
            id="model-weights",
            name="Fine-tuned model weights",
            kind="model-weights",
            description="contracts-ft-v3.pt — the firm's private fine-tuned contract model (~300 MB).",
            ref=f"pvc/{config.MODEL_WEIGHTS_PVC}",
            status="clean",
            statusSince=ts,
        ),
        Asset(
            id="training",
            name="Model training job",
            kind="job",
            description="Ongoing GPU fine-tuning run for the firm.",
            ref=f"pod/{training}",
            status="clean",
            statusSince=ts,
        ),
        Asset(
            id="notebook",
            name="Data-science notebook",
            kind="pod",
            description="A researcher's notebook. Holds an over-privileged service-account token.",
            ref=f"pod/{notebook}",
            status="clean",
            statusSince=ts,
        ),
        Asset(
            id="node",
            name="GPU node",
            kind="node",
            description="The single Tesla T4 node running all firm workloads.",
            ref=f"node/{node_name}",
            status="clean",
            statusSince=ts,
        ),
    ]
