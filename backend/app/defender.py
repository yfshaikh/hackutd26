"""Defender: deterministic detection + Nemotron reasoning + policy-gated tools.

Detection is pure code (a pod watch / telemetry poll). When it fires, Nemotron
reasons over the real cluster state and calls real Kubernetes tools. The
autonomy policy is enforced here, in code, BEFORE every tool call — never left
to the model. Every action is logged to the timeline and to logs/decisions.jsonl.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from kubernetes import client

from . import config
from .cluster import quarantine_np_names, read_gpus
from .hub import store
from .k8s import (
    ApiException,
    admin,
    admin_batch,
    admin_core,
    admin_net,
    admin_rbac,
    first_pod_name,
)
from .models import Approval, IncidentRecord, RecordAction, now_iso

AGENT = "Sentinel (Nemotron)"

# Pending actions awaiting human approval: approval_id -> (tool_name, args, rationale)
pending_actions: dict[str, tuple[str, dict, str]] = {}

# Dedupe: finding keys we have already escalated to the agent this incident.
_handled: set[str] = set()
_nemotron_announced = False

# Nemotron's message/reasoning text for the round currently being executed. Set by
# run_agent before it dispatches that round's tool calls, so each resulting timeline
# entry can carry the real model reasoning that led to it (Task 3).
_round_reasoning: str = ""


# ---------------------------------------------------------------------------
# Decision log (judges asked for logs)
# ---------------------------------------------------------------------------
def _log_decision(record: dict) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), **record}
    with config.DECISIONS_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Incident record helpers
# ---------------------------------------------------------------------------
def ensure_incident() -> IncidentRecord:
    if store.record is None:
        rec = IncidentRecord(
            id=f"inc-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:4]}",
            title="Compromise of law-firm GPU workloads",
            status="open",
            phase="detection",
            detectedAt=now_iso(),
            reportedBy=AGENT,
            categories=["unauthorized-access"],
            severity="high",
            vector="Over-privileged notebook service-account token (RBAC over-grant in lawfirm)",
            affectedSystems=[],
            actionsTaken=[],
            nextSteps=["Contain attacker workloads", "Determine exfiltration scope"],
            updatedAt=now_iso(),
        )
        store.set_record(rec)
    return store.record


def record_action(text: str, by: str = AGENT) -> None:
    rec = ensure_incident()
    rec.actionsTaken.append(RecordAction(ts=now_iso(), by=by, text=text))
    rec.updatedAt = now_iso()
    store.set_record(rec)


def _record_merge(fields: dict) -> None:
    rec = ensure_incident()
    for k, v in fields.items():
        if not hasattr(rec, k):
            continue
        if k in ("categories", "affectedSystems", "nextSteps") and isinstance(v, list):
            cur = getattr(rec, k)
            for item in v:
                if item not in cur:
                    cur.append(item)
        else:
            setattr(rec, k, v)
    rec.updatedAt = now_iso()
    store.set_record(rec)


# ---------------------------------------------------------------------------
# Autonomy policy (enforced in code)
# ---------------------------------------------------------------------------
READ_TOOLS = {"list_pods", "describe_pod", "get_pod_logs", "gpu_status"}
RECORD_TOOLS = {"update_scope", "update_incident_record"}


def _pod_owner_label(name: str, namespace: str) -> str | None:
    try:
        p = admin_core().read_namespaced_pod(name, namespace)
        return (p.metadata.labels or {}).get("owner")
    except ApiException:
        return None


def classify(tool: str, args: dict) -> tuple[str, str, str]:
    """Return (mode, reason, policy_reason). mode in {autonomous, needs-approval}."""
    if tool in READ_TOOLS or tool in RECORD_TOOLS:
        return "autonomous", "read-only or record update", ""
    if tool == "quarantine_pod":
        return "autonomous", "reversible, affects attacker only", ""
    if tool == "delete_cronjob":
        name = args.get("name", "")
        if name in config.CRONJOB_ALLOWLIST:
            return "needs-approval", "cronjob is on the allowlist", "touches legitimate scheduled work"
        return "autonomous", "reversible, affects attacker only", ""
    if tool == "delete_pod":
        owner = _pod_owner_label(args.get("name", ""), args.get("namespace", config.LAWFIRM_NS))
        if owner in ("law-firm", "platform"):
            return "needs-approval", "pod belongs to legitimate work", "deletes a legitimate workload"
        return "autonomous", "unknown pod, affects attacker only", ""
    if tool == "revoke_service_account":
        return "needs-approval", "revokes an identity real users rely on", "breaks the notebook"
    if tool == "cordon_node":
        return "needs-approval", "cordons a node running real jobs", "affects legitimate workloads on the node"
    return "needs-approval", "unrecognized action", "unknown impact"


# ---------------------------------------------------------------------------
# Raw tool executors (the real Kubernetes actions)
# ---------------------------------------------------------------------------
def _do_list_pods(namespace: str = config.LAWFIRM_NS) -> str:
    core = admin_core()
    quarantined = quarantine_np_names()
    rows = []
    for p in core.list_namespaced_pod(namespace).items:
        owner = (p.metadata.labels or {}).get("owner", "<none>")
        gpu = any(
            "nvidia.com/gpu" in (c.resources.limits or {}) for c in (p.spec.containers or [])
        )
        rows.append(
            f"{p.metadata.name} phase={p.status.phase} owner={owner} gpu={gpu} "
            f"quarantined={f'quarantine-{p.metadata.name}' in quarantined}"
        )
    return "\n".join(rows) or "(no pods)"


def _do_describe_pod(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    try:
        p = admin_core().read_namespaced_pod(name, namespace)
    except ApiException as e:
        return f"error: {e.reason}"
    vols = [
        v.persistent_volume_claim.claim_name
        for v in (p.spec.volumes or [])
        if v.persistent_volume_claim
    ]
    cmds = [c.command for c in (p.spec.containers or [])]
    return json.dumps(
        {
            "name": name,
            "labels": p.metadata.labels or {},
            "node": p.spec.node_name,
            "phase": p.status.phase,
            "images": [c.image for c in (p.spec.containers or [])],
            "commands": cmds,
            "pvcs": vols,
        }
    )


def _do_get_pod_logs(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    try:
        return admin_core().read_namespaced_pod_log(name, namespace, tail_lines=40) or "(empty)"
    except ApiException as e:
        return f"error: {e.reason}"


def _do_gpu_status() -> str:
    gpus, total = read_gpus()
    return json.dumps(
        {"total_utilization": total, "gpus": [g.model_dump() for g in gpus]}
    )


def _do_delete_pod(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    admin_core().delete_namespaced_pod(name, namespace, body=opts)
    return f"deleted pod/{name} in {namespace}"


def _do_quarantine_pod(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    core = admin_core()
    label_key = "hackutd/quarantine-target"
    try:
        core.patch_namespaced_pod(
            name, namespace, {"metadata": {"labels": {label_key: name}}}
        )
    except ApiException as e:
        return f"error labeling pod: {e.reason}"
    np = client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name=f"quarantine-{name}", namespace=namespace, labels={"hackutd/quarantine": "true"}
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(match_labels={label_key: name}),
            policy_types=["Ingress", "Egress"],
            ingress=[],
            egress=[],
        ),
    )
    try:
        admin_net().create_namespaced_network_policy(namespace, np)
    except ApiException as e:
        if e.status != 409:
            return f"error: {e.reason}"
    return f"quarantined pod/{name} with deny-all NetworkPolicy quarantine-{name}"


def _do_delete_cronjob(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    admin_batch().delete_namespaced_cron_job(name, namespace, body=opts)
    return f"deleted cronjob/{name} in {namespace}"


def _do_revoke_service_account() -> str:
    opts = client.V1DeleteOptions(grace_period_seconds=0)
    admin_rbac().delete_namespaced_role_binding("notebook-dev", config.LAWFIRM_NS, body=opts)
    return "deleted RoleBinding notebook-dev in lawfirm (stolen token can no longer act)"


def _do_cordon_node(name: str) -> str:
    admin_core().patch_node(name, {"spec": {"unschedulable": True}})
    return f"cordoned node {name}"


_ASSET_STATUSES = {"clean", "investigating", "exfiltrated", "encrypted", "contained"}


def _do_update_scope(asset: str, status: str, note: str = "") -> str:
    if status not in _ASSET_STATUSES:
        return f"ERROR, not applied: status={status!r} is not one of {sorted(_ASSET_STATUSES)}"
    a = store.set_asset_status(asset, status, note or None)
    return f"asset {asset} -> {status}" if a else f"unknown asset {asset}"


# Allowed values mirror console/src/types.ts. The model's output is untrusted input: anything outside
# these is rejected with an error the model can read and correct, instead of reaching the UI.
_RECORD_ENUMS = {
    "status": {"monitoring", "open", "contained", "resolved"},
    "phase": {"preparation", "detection", "analysis", "containment", "eradication", "recovery", "post-incident"},
    "severity": {"info", "low", "medium", "high", "critical"},
}
_RECORD_LISTS = {"affectedSystems", "nextSteps", "categories"}
_RECORD_TEXT = {"vector", "title"}


def _do_update_incident_record(fields: dict) -> str:
    clean, errors = {}, []
    for k, v in (fields or {}).items():
        if k in _RECORD_ENUMS:
            if v in _RECORD_ENUMS[k]:
                clean[k] = v
            else:
                errors.append(f"{k}={v!r} is not one of {sorted(_RECORD_ENUMS[k])}")
        elif k in _RECORD_LISTS and isinstance(v, list) and all(isinstance(x, str) for x in v):
            clean[k] = v
        elif k in _RECORD_TEXT and isinstance(v, str):
            clean[k] = v
        else:
            errors.append(f"{k} is not an editable field (or has the wrong type)")
    if clean:
        _record_merge(clean)
    if errors:
        return "ERROR, not applied: " + "; ".join(errors) + (f". Applied: {sorted(clean)}" if clean else "")
    return "incident record updated"


_RAW = {
    "list_pods": _do_list_pods,
    "describe_pod": _do_describe_pod,
    "get_pod_logs": _do_get_pod_logs,
    "gpu_status": _do_gpu_status,
    "delete_pod": _do_delete_pod,
    "quarantine_pod": _do_quarantine_pod,
    "delete_cronjob": _do_delete_cronjob,
    "revoke_service_account": _do_revoke_service_account,
    "cordon_node": _do_cordon_node,
    "update_scope": _do_update_scope,
    "update_incident_record": _do_update_incident_record,
}

_TOOL_TARGET = lambda args: args.get("name") or args.get("asset") or args.get("namespace") or ""


def _summarize_call(tool: str, args: dict) -> str:
    inner = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{tool}({inner})"


def _pod_logs_for(tool: str, args: dict) -> str | None:
    """Relevant pod logs for a pod-targeting tool (Task 3). Read before deletion."""
    if tool not in ("delete_pod", "quarantine_pod"):
        return None
    name = args.get("name")
    if not name:
        return None
    try:
        logs = admin_core().read_namespaced_pod_log(
            name, args.get("namespace", config.LAWFIRM_NS), tail_lines=12
        )
    except ApiException as e:
        return f"(logs unavailable: {e.reason})"
    return logs.strip() or "(no output)"


def run_tool_approved(tool: str, args: dict, approval_id: str, by: str) -> str:
    """Execute a tool that a human just approved. Bypasses the pending gate."""
    pod_logs = _pod_logs_for(tool, args)
    result = _RAW[tool](**args)
    store.add_timeline(
        kind="agent",
        actor=AGENT,
        text=f"Executed approved action: {_summarize_call(tool, args)} — {result}",
        severity="high",
        autonomy={"mode": "needs-approval", "reason": "approved by " + by, "approvalId": approval_id},
        tool=_summarize_call(tool, args),
        target=_TOOL_TARGET(args),
        tool_args=args,
        tool_result=result,
        pod_logs=pod_logs,
    )
    record_action(f"{_summarize_call(tool, args)} — {result} (approved by {by})")
    _log_decision({"tool": tool, "args": args, "mode": "needs-approval",
                   "decision": "approved", "by": by, "result": result})
    return result


def _dispatch(tool: str, args: dict) -> str:
    """Policy-gated dispatch used by the agent loop. Returns text for the model."""
    if tool not in _RAW:
        return f"error: unknown tool {tool}"
    mode, reason, policy_reason = classify(tool, args)

    if mode == "needs-approval":
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:8]}",
            requestedAt=now_iso(),
            requestedBy=AGENT,
            action=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            rationale=reason,
            policyReason=policy_reason,
            impact=_impact_for(tool, args),
            status="pending",
        )
        store.upsert_approval(approval)
        pending_actions[approval.id] = (tool, args, reason)
        store.add_timeline(
            kind="agent",
            actor=AGENT,
            text=f"Requesting human approval to {_summarize_call(tool, args)} — {policy_reason}.",
            severity="high",
            autonomy={"mode": "needs-approval", "reason": policy_reason, "approvalId": approval.id},
            tool=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            tool_args=args,
            reasoning=_round_reasoning or None,
        )
        _log_decision({"tool": tool, "args": args, "mode": "needs-approval",
                       "decision": "pending", "approvalId": approval.id, "policyReason": policy_reason})
        return (
            f"POLICY: '{tool}' needs human approval ({policy_reason}). "
            f"Approval {approval.id} created and is pending. Do not retry; continue with other containment."
        )

    # Autonomous
    pod_logs = _pod_logs_for(tool, args)  # read before a delete removes the pod
    try:
        result = _RAW[tool](**args)
    except ApiException as e:
        result = f"error: {e.reason}"
    except Exception as e:  # noqa: BLE001
        result = f"error: {e}"
    if tool not in READ_TOOLS:
        store.add_timeline(
            kind="agent",
            actor=AGENT,
            text=f"{_summarize_call(tool, args)} — {result}",
            severity="medium",
            autonomy={"mode": "autonomous", "reason": reason},
            tool=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            tool_args=args,
            tool_result=result,
            reasoning=_round_reasoning or None,
            pod_logs=pod_logs,
        )
        record_action(f"{_summarize_call(tool, args)} — {result}")
    _log_decision({"tool": tool, "args": args, "mode": mode, "decision": "executed", "result": result})
    return result


def _impact_for(tool: str, args: dict) -> str:
    if tool == "revoke_service_account":
        return "The notebook loses API access; researchers cannot launch jobs until re-provisioned."
    if tool == "cordon_node":
        return "No new pods schedule on the node; running firm workloads keep running."
    if tool == "delete_pod":
        return f"Pod {args.get('name')} is terminated."
    return "See rationale."


# ---------------------------------------------------------------------------
# Nemotron tool specs
# ---------------------------------------------------------------------------
def _tool_schemas() -> list[dict]:
    def fn(name, desc, props, required):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }

    ns = {"namespace": {"type": "string", "description": "defaults to lawfirm"}}
    nm = {"name": {"type": "string"}}
    return [
        fn("list_pods", "List pods in a namespace with owner/gpu/quarantine status.", ns, []),
        fn("describe_pod", "Show a pod's labels, images, commands and mounted PVCs.", {**nm, **ns}, ["name"]),
        fn("get_pod_logs", "Tail a pod's logs.", {**nm, **ns}, ["name"]),
        fn("gpu_status", "Current GPU utilization and memory from nvidia-smi.", {}, []),
        fn("delete_pod", "Delete a pod. Autonomous only for unknown (attacker) pods.", {**nm, **ns}, ["name"]),
        fn("quarantine_pod", "Isolate a pod with a deny-all NetworkPolicy.", {**nm, **ns}, ["name"]),
        fn("delete_cronjob", "Delete a CronJob not on the allowlist.", {**nm, **ns}, ["name"]),
        fn("revoke_service_account", "Delete the notebook-dev RoleBinding. Needs approval.", {}, []),
        fn("cordon_node", "Cordon a node. Needs approval.", nm, ["name"]),
        fn(
            "update_scope",
            "Set an asset's scope status (clean|investigating|exfiltrated|encrypted|contained).",
            {"asset": {"type": "string"}, "status": {"type": "string"}, "note": {"type": "string"}},
            ["asset", "status"],
        ),
        fn(
            "update_incident_record",
            "Merge fields into the incident record. Use only the allowed values; put free-text progress in nextSteps.",
            {"fields": {"type": "object", "additionalProperties": False, "properties": {
                "status": {"type": "string", "enum": sorted(_RECORD_ENUMS["status"])},
                "phase": {"type": "string", "enum": sorted(_RECORD_ENUMS["phase"])},
                "severity": {"type": "string", "enum": sorted(_RECORD_ENUMS["severity"])},
                "affectedSystems": {"type": "array", "items": {"type": "string"}},
                "nextSteps": {"type": "array", "items": {"type": "string"}},
                "categories": {"type": "array", "items": {"type": "string"}},
                "vector": {"type": "string"},
            }}},
            ["fields"],
        ),
    ]


SYSTEM_PROMPT = (
    "You are Sentinel, the autonomous defender for a law firm's GPU cluster, built on NVIDIA "
    "Nemotron. An attacker has compromised workloads in the 'lawfirm' Kubernetes namespace using a "
    "stolen service-account token. Your job: investigate with the read tools, then contain the "
    "attacker, determine the exfiltration scope, and keep the incident record current.\n\n"
    "AUTONOMY POLICY (the backend enforces this; respect it): you may act autonomously to delete "
    "UNKNOWN pods (no owner label), quarantine pods, delete non-allowlisted cronjobs, and update "
    "scope/record. Actions that touch legitimate work — revoke_service_account, cordon_node, or "
    "deleting an OWNED pod — require human approval; request them when warranted but do not expect "
    "them to run immediately. Never delete or disrupt pods owned by 'law-firm' or 'platform'.\n\n"
    "Work in steps: inspect first, then contain the miner and any exfiltration/persistence, then "
    "update the scope of affected assets and the incident record.\n\n"
    "ROOT CAUSE: deleting the attacker's objects is not enough while the stolen token still works. "
    "Once you have contained the attacker's pods, CALL revoke_service_account (it will be routed to "
    "a human for approval; that is expected). Do not just list it as a next step. Set the notebook "
    "asset to 'investigating' since it was the entry point.\n\n"
    "Asset ids for update_scope are exactly: model-weights, training, notebook, node. "
    "Never lower severity after confirmed exfiltration. Call update_incident_record to "
    "advance the phase (detection->containment->eradication) and list next steps. Be decisive and "
    "concise. When containment is done, stop calling tools and give a one-paragraph summary."
)


def nemotron_configured() -> bool:
    return config.nvidia_api_key() is not None


def _client():
    from openai import OpenAI

    return OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=config.nvidia_api_key())


def run_agent(trigger: str) -> None:
    """Blocking: run the Nemotron tool-calling loop for a detection trigger."""
    if not nemotron_configured():
        global _nemotron_announced
        if not _nemotron_announced:
            _nemotron_announced = True
            store.add_timeline(
                kind="system",
                actor="System",
                text="Nemotron not configured: set OPENROUTER_API_KEY or NVIDIA_API_KEY in backend/.env. "
                "Detection is running; automated containment is paused until a key is set.",
                severity="medium",
            )
        return

    try:
        oai = _client()
    except Exception as e:  # noqa: BLE001
        store.add_timeline(kind="system", actor="System",
                           text=f"Nemotron client error: {e}", severity="medium")
        return

    ctx = (
        f"Detection trigger: {trigger}\n\n"
        f"Current lawfirm pods:\n{_do_list_pods()}\n\n"
        f"GPU: {_do_gpu_status()}\n\n"
        "Investigate and contain. Remember the autonomy policy."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ctx},
    ]
    tools = _tool_schemas()

    for _round in range(8):
        try:
            resp = oai.chat.completions.create(
                model=config.NEMOTRON_MODEL,
                messages=messages,
                tools=tools,
                temperature=0.2,
                max_tokens=4096,   # reasoning models spend part of this on thinking
            )
        except Exception as e:  # noqa: BLE001
            store.add_timeline(kind="system", actor="System",
                               text=f"Nemotron call failed: {e}", severity="medium")
            return
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        # Carry this round's real model reasoning onto the actions it triggers (Task 3).
        # Some Nemotron deployments surface it as reasoning_content rather than content.
        global _round_reasoning
        _round_reasoning = (msg.content or "").strip() or (getattr(msg, "reasoning_content", "") or "").strip()
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ] or None,
            }
        )
        if msg.content and not tool_calls:
            store.add_timeline(kind="agent", actor=AGENT, text=msg.content.strip(), severity="info")
            return
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _dispatch(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:2000]})
    store.add_timeline(kind="agent", actor=AGENT,
                       text="Containment loop reached its step limit; see actions above.", severity="info")


# ---------------------------------------------------------------------------
# Deterministic detection
# ---------------------------------------------------------------------------
def _detect() -> list[tuple[str, str]]:
    """Return list of (dedupe_key, human trigger) findings from real state."""
    findings: list[tuple[str, str]] = []
    core = admin_core()
    try:
        pods = core.list_namespaced_pod(config.LAWFIRM_NS).items
    except ApiException:
        return findings

    for p in pods:
        name = p.metadata.name
        labels = p.metadata.labels or {}
        owner = labels.get("owner")
        if p.status.phase in ("Succeeded", "Failed") and p.metadata.deletion_timestamp:
            continue
        # unknown pod in lawfirm (every legitimate workload carries owner=law-firm)
        if owner is None:
            findings.append((f"rogue-pod:{name}", f"Unknown pod '{name}' with no owner label in lawfirm."))
        # pod other than model-server mounting the weights PVC
        mounts_weights = any(
            v.persistent_volume_claim and v.persistent_volume_claim.claim_name == config.MODEL_WEIGHTS_PVC
            for v in (p.spec.volumes or [])
        )
        if mounts_weights and not name.startswith(config.WEIGHTS_MOUNT_ALLOWLIST):
            findings.append((f"weights-mount:{name}", f"Pod '{name}' mounts model-weights but is not the model server."))

    # cronjobs not on the allowlist
    try:
        for cj in admin_batch().list_namespaced_cron_job(config.LAWFIRM_NS).items:
            if cj.metadata.name not in config.CRONJOB_ALLOWLIST:
                findings.append((f"rogue-cronjob:{cj.metadata.name}",
                                 f"Unexpected CronJob '{cj.metadata.name}' in lawfirm (persistence)."))
    except ApiException:
        pass

    # GPU spike not explained by known pods
    gpus, total = read_gpus()
    rogue_gpu = any(
        (p.metadata.labels or {}).get("owner") is None
        and any("nvidia.com/gpu" in (c.resources.limits or {}) for c in (p.spec.containers or []))
        for p in pods
    )
    if total >= 80 and rogue_gpu:
        findings.append(("gpu-spike", f"GPU utilization {total:.0f}% driven by an unknown pod."))
    return findings


def _check_exfil_evidence() -> None:
    """After exfil, read the real drop-site log for the 'received' line.

    Only runs once an incident is already open, so a stale log line from a
    previous (already-reset) run can never open a fresh incident on its own.
    """
    if store.record is None:
        return
    pod = first_pod_name(admin(), config.DROP_NS, "app=drop")
    if not pod:
        return
    try:
        logs = admin_core().read_namespaced_pod_log(pod, config.DROP_NS, tail_lines=20)
    except ApiException:
        return
    for line in logs.splitlines():
        if "received" in line and config.WEIGHTS_FILE in line:
            parts = line.split()
            n = next((int(x) for x in parts if x.isdigit()), 0)
            mib = round(n / 2**20, 1)
            if store.assets.get("model-weights") and store.assets["model-weights"].status != "exfiltrated":
                store.set_asset_status(
                    "model-weights", "exfiltrated",
                    f"{n} bytes ({mib} MiB) left the cluster to the attacker drop site.",
                )
                due = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
                _record_merge({
                    "notificationDueAt": due,
                    "categories": ["data-exfiltration"],
                    "severity": "critical",
                    "affectedSystems": ["pvc/model-weights"],
                })
                store.add_timeline(
                    kind="system", actor="System",
                    text=f"Drop-site evidence: {line.strip()} — model weights confirmed exfiltrated ({mib} MiB).",
                    severity="critical",
                )
            return


async def detection_loop() -> None:
    """Background task: poll for threats, escalate new ones to Nemotron."""
    while True:
        try:
            findings = await asyncio.to_thread(_detect)
            await asyncio.to_thread(_check_exfil_evidence)
            new = [(k, t) for (k, t) in findings if k not in _handled]
            if new:
                for k, t in new:
                    _handled.add(k)
                    ensure_incident()
                    sys_sev = "critical" if k.startswith("weights") else "high"
                    tgt = k.split(":", 1)[1] if ":" in k else None
                    store.add_timeline(kind="system", actor="Detector",
                                       text=f"Detection: {t}", severity=sys_sev, target=tgt)
                    _record_merge({"affectedSystems": [tgt] if tgt else [], "phase": "containment"})
                trigger = "; ".join(t for _, t in new)
                await asyncio.to_thread(run_agent, trigger)
            if not findings and not _handled:
                pass
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(4)


def reset_detection_state() -> None:
    _handled.clear()
    pending_actions.clear()
