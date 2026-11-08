"""Defender: deterministic detection + Nemotron reasoning + policy-gated tools.

Detection is pure code (a pod watch / telemetry poll). When it fires, Nemotron
reasons over the real cluster state and calls real Kubernetes tools. The
autonomy policy is enforced here, in code, BEFORE every tool call — never left
to the model. Every action is logged to the timeline and to logs/decisions.jsonl.

READING MAP (sections in order, top to bottom):
  1. Module state           pending_actions / _handled / _round_reasoning — the
                            in-memory working set for the incident in flight.
  2. Decision log           _log_decision -> logs/decisions.jsonl (one line per
                            tool call). The evals + /defender/metrics read this.
  3. Incident record        ensure_incident / record_action / _record_merge.
  4. Autonomy policy        READ_TOOLS, classify() — the heart: decides per call
                            whether a tool runs autonomously or needs approval.
  5. Runbook                _RUNBOOK — ranks proposed actions + cites a step.
  6. Tool executors         _do_* — the REAL Kubernetes calls. Reads go through
                            the read-only agent identity, writes through the
                            executor identity (see k8s.py); detection stays admin.
  7. verify_readonly_identity  startup proof the agent SA cannot write (403).
  8. Approval + dispatch    run_tool_approved / _dispatch — the gate: needs-approval
                            actions become pending; autonomous ones run now.
  9. Nemotron agents        _tool_schemas, the three role prompts, _run_role() and
                            run_agent() — the Triage->Investigator->Advisor pipeline, the
                            hypothesis-driven Investigator, and the bounded
                            verify-and-reconverge pass after the Advisor contains.
 10. Detection              _detect / _check_exfil_evidence / detection_tick /
                            detection_loop — what fires the agent, every 4s.
 11. Metrics                metrics() — current-incident outcomes from the log.

The through-line is the NMC pattern: the agent proposes, CODE enforces.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from kubernetes import client

from . import config
from .cluster import quarantine_np_names, read_gpus
from .hub import store
from .k8s import (
    AgentIdentityUnavailable,
    ApiException,
    admin,
    admin_batch,
    admin_core,
    agent_readonly_core,
    executor_batch,
    executor_core,
    executor_net,
    executor_rbac,
    first_pod_name,
)
from .models import Approval, Hypothesis, IncidentRecord, RecordAction, now_iso

AGENT = "Sentinel (Nemotron)"  # umbrella name for incident bookkeeping (reportedBy, record_action)

# THE TEAM (for a learner): "Sentinel" is not one agent — it's a pipeline of three
# Nemotron agents that hand the incident down the line, plus a non-LLM write identity:
#   triage       — first responder: classifies severity/phase, decides what to chase.
#   investigator — forensics: reads logs/pods, maps which assets were hit (the scope).
#   advisor      — containment lead: proposes + runs the ranked remediation (the only
#                  stage with mutating tools, so the approve/executor gate lives here).
#   executor     — NOT a model: the privileged identity that actually applies a fix the
#                  Advisor got cleared (autonomously or after a human approves).
# Each reasoning agent is a separate model call with its own prompt, tool subset and
# model (Triage/Investigator run cheap+fast, Advisor runs the heavy model). Every
# timeline entry carries which one emitted it, in the `agent` field.
TRIAGE, INVESTIGATOR, ADVISOR, EXECUTOR = "triage", "investigator", "advisor", "executor"
_AGENT_NAME = {
    TRIAGE: "Triage (Nemotron)",
    INVESTIGATOR: "Investigator (Nemotron)",
    ADVISOR: "Advisor (Nemotron)",
    EXECUTOR: "Executor",
}

# Pending actions awaiting human approval: approval_id -> (tool_name, args, rationale)
pending_actions: dict[str, tuple[str, dict, str]] = {}

# Dedupe: finding keys we have already escalated to the agent this incident.
_handled: set[str] = set()
_nemotron_announced = False

# Nemotron's message/reasoning text for the round currently being executed. Set by
# run_agent before it dispatches that round's tool calls, so each resulting timeline
# entry can carry the real model reasoning that led to it (Task 3).
_round_reasoning: str = ""

# Which pipeline agent is running right now, so _dispatch stamps its entries with the
# right actor. Set by _run_role before each stage. Defaults to advisor (the only stage
# that dispatches mutating tools, so a stray proposal is attributed sensibly).
_current_agent: str = ADVISOR


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
        # nextSteps is the CURRENT plan: replace it, so re-runs don't pile up stale steps.
        # Categories / affected systems accumulate (union) as more of the attack is found.
        if k in ("categories", "affectedSystems") and isinstance(v, list):
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
# THE BIG IDEA (for a learner): an AI agent is non-deterministic — you cannot
# fully trust it to decide, on its own, what it's allowed to do. So we don't ask
# the model "are you allowed to do this?" We hard-code the rule here in Python and
# check it BEFORE every action the model requests. The model proposes; this code
# disposes. That's the single most important safety property in the whole project.
#
# READ_TOOLS = safe look-only actions (list/describe pods, read logs, GPU stats).
# RECORD_TOOLS = updating our own incident paperwork (scope + the NIST record).
# Neither changes the cluster, so both always run autonomously (no approval).
READ_TOOLS = {"list_pods", "describe_pod", "get_pod_logs", "gpu_status", "get_runbook"}
RECORD_TOOLS = {"update_scope", "update_incident_record", "record_hypothesis"}
# External-service lookups the agents make to enrich the incident with real-world data — a live
# CVE/NVD lookup for the exploited vector and a crypto-price lookup to size the stolen GPU compute
# (see enrich.py). Read-only and off-cluster, so they always run autonomously; shown in the main
# timeline (not trace-only), because citing a real CVE/impact is part of the story.
ENRICH_TOOLS = {"lookup_cve", "mining_impact"}


def _pod_owner_label(name: str, namespace: str) -> str | None:
    try:
        p = admin_core().read_namespaced_pod(name, namespace)
        return (p.metadata.labels or {}).get("owner")
    except ApiException:
        return None


def classify(tool: str, args: dict) -> tuple[str, str, str]:
    """Decide how a single proposed action may run. Returns (mode, reason, policy_reason);
    mode is "autonomous" (run it now) or "needs-approval" (hold for a human to approve).

    The rule of thumb: the agent may act on its own ONLY when the action is reversible
    and hits the attacker alone. Anything that could disrupt the law firm's real work —
    deleting a legitimate pod, revoking the identity real users need, cordoning a node —
    is held for a human, because a mistake there is the kind that pages you at 3am.
    """
    if tool in READ_TOOLS or tool in RECORD_TOOLS or tool in ENRICH_TOOLS:
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


# Runbook: the ranked remediation playbook the agent cites when it proposes an action.
# Lower rank = do first (stop the bleeding, then persistence, then identity).
# ponytail: static table keyed by tool; a config-driven runbook is the Future item.
_RUNBOOK = {
    "quarantine_pod":         {"rank": 1, "runbookRef": "RB-02#isolate",  "risk": "low",    "reversible": True},
    "delete_pod":             {"rank": 2, "runbookRef": "RB-01#contain",  "risk": "low",    "reversible": False},
    "delete_cronjob":         {"rank": 3, "runbookRef": "RB-03#persist",  "risk": "low",    "reversible": False},
    "revoke_service_account": {"rank": 4, "runbookRef": "RB-04#identity", "risk": "high",   "reversible": False},
    "cordon_node":            {"rank": 5, "runbookRef": "RB-05#node",     "risk": "medium", "reversible": True},
}


def _runbook_for(tool: str) -> dict:
    return _RUNBOOK.get(tool, {"rank": 99, "runbookRef": "RB-00#unknown", "risk": "high", "reversible": False})


# ---------------------------------------------------------------------------
# Raw tool executors (the real Kubernetes actions)
# ---------------------------------------------------------------------------
# TWO IDENTITIES (for a learner): in Kubernetes, every request carries an identity
# whose permissions (RBAC) the cluster enforces. We give this agent TWO of them:
#   * agent_readonly_core() — can ONLY look (list/read). Used for investigation.
#   * executor_core()/batch()/net()/rbac() — can change things. Used ONLY after a
#     human approves (or the policy above cleared the action as attacker-only).
# So even if the model were tricked into "delete everything", its read-only identity
# is physically unable to — the cluster itself refuses. Code is one guard, RBAC is
# the second. (The backend's own monitoring keeps using the admin identity; that's
# the trusted SIEM, not the agent.)
def _do_list_pods(namespace: str = config.LAWFIRM_NS) -> str:
    try:
        core = agent_readonly_core()  # the agent investigates read-only
    except AgentIdentityUnavailable as e:
        return f"error: {e}"
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
        p = agent_readonly_core().read_namespaced_pod(name, namespace)
    except AgentIdentityUnavailable as e:
        return f"error: {e}"
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
        return agent_readonly_core().read_namespaced_pod_log(name, namespace, tail_lines=40) or "(empty)"
    except AgentIdentityUnavailable as e:
        return f"error: {e}"
    except ApiException as e:
        return f"error: {e.reason}"


def _do_gpu_status() -> str:
    gpus, total = read_gpus()
    return json.dumps(
        {"total_utilization": total, "gpus": [g.model_dump() for g in gpus]}
    )


def _require_lawfirm(namespace: str) -> str | None:
    """Defense-in-depth: the executor only ever acts in lawfirm, even if RBAC were looser.
    Returns an error string to refuse, or None to proceed."""
    if namespace != config.LAWFIRM_NS:
        return f"refused: executor only acts in {config.LAWFIRM_NS}, not {namespace!r}"
    return None


def _do_delete_pod(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    if (err := _require_lawfirm(namespace)):
        return err
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    executor_core().delete_namespaced_pod(name, namespace, body=opts)
    return f"deleted pod/{name} in {namespace}"


def _do_quarantine_pod(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    if (err := _require_lawfirm(namespace)):
        return err
    core = executor_core()
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
        executor_net().create_namespaced_network_policy(namespace, np)
    except ApiException as e:
        if e.status != 409:
            return f"error: {e.reason}"
    return f"quarantined pod/{name} with deny-all NetworkPolicy quarantine-{name}"


def _do_delete_cronjob(name: str, namespace: str = config.LAWFIRM_NS) -> str:
    if (err := _require_lawfirm(namespace)):
        return err
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    executor_batch().delete_namespaced_cron_job(name, namespace, body=opts)
    return f"deleted cronjob/{name} in {namespace}"


def _do_revoke_service_account() -> str:
    opts = client.V1DeleteOptions(grace_period_seconds=0)
    executor_rbac().delete_namespaced_role_binding("notebook-dev", config.LAWFIRM_NS, body=opts)
    return "deleted RoleBinding notebook-dev in lawfirm (stolen token can no longer act)"


def _do_cordon_node(name: str) -> str:
    executor_core().patch_node(name, {"spec": {"unschedulable": True}})
    return f"cordoned node {name}"


def verify_readonly_identity() -> str:
    """Prove the agent's own identity cannot mutate the cluster: attempt a delete with the
    read-only client and expect a 403 from RBAC. 404 (reached the not-found check) means the
    identity is NOT read-only — the admin fallback, or an over-broad role. Logged as evidence.

    For a learner: this is a self-test run once at startup. We deliberately try to delete a
    pod that doesn't exist. If RBAC is set up right, the cluster rejects it with 403
    Forbidden *before* even checking whether the pod exists — proving the agent truly can't
    write. If we instead got 404 Not-Found, it means the delete was allowed through (bad!),
    so the split isn't actually protecting anything. We log which one happened as evidence."""
    try:
        agent_readonly_core().delete_namespaced_pod(
            "readonly-selfcheck-does-not-exist", config.LAWFIRM_NS,
            body=client.V1DeleteOptions(grace_period_seconds=0),
        )
        result, ok = "FAIL: read-only identity was allowed to delete (RBAC too broad)", False
    except AgentIdentityUnavailable as e:
        result, ok = f"NOT verified: {e}", False
    except ApiException as e:
        if e.status == 403:
            result, ok = f"confirmed read-only: delete denied by RBAC (403 {e.reason})", True
        elif e.status == 404:
            result, ok = "NOT read-only: delete reached the API (404) — admin fallback or over-broad role", False
        else:
            result, ok = f"inconclusive: {e.status} {e.reason}", False
    store.add_timeline(kind="system", actor="Detector",
                       text=f"Agent identity self-check — {result}.",
                       severity="info" if ok else "high")
    _log_decision({"tool": "verify_readonly_identity", "mode": "self-check",
                   "decision": "verified" if ok else "failed", "result": result})
    return result


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
_RECORD_TEXT = {"vector", "title", "summary", "impact", "rootCause"}
_VERDICTS = {"possible", "likely", "confirmed", "ruled_out"}


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


# Incident runbooks: one Markdown file per scenario in backend/runbooks/. The agents read them
# through get_runbook; the console renders the same files on its Runbooks page.
RUNBOOK_DIR = config.BACKEND_DIR / "runbooks"


def runbooks() -> dict[str, str]:
    """Every runbook, id (file stem) -> Markdown. Read fresh so an edited file takes effect."""
    return {p.stem: p.read_text() for p in sorted(RUNBOOK_DIR.glob("*.md"))}


def _do_get_runbook(scenario: str = "") -> str:
    books = runbooks()
    key = scenario.strip().lower()
    if key in books:
        return books[key]
    return f"No runbook named {scenario!r}. Available: {', '.join(books)}"


def _do_record_hypothesis(name: str = "", verdict: str = "", evidence: str = "") -> str:
    """File (or update) one hypothesis on the record. Keyed by name, so re-filing the same
    hypothesis as evidence changes moves its verdict instead of adding a duplicate."""
    name = name.strip().lower()
    if not name:
        return "ERROR, not applied: name is required"
    if verdict not in _VERDICTS:
        return f"ERROR, not applied: verdict={verdict!r} is not one of {sorted(_VERDICTS)}"
    rec = ensure_incident()
    h = Hypothesis(name=name, verdict=verdict, evidence=evidence.strip(), ts=now_iso())
    rec.hypotheses = [x for x in rec.hypotheses if x.name != name] + [h]
    rec.updatedAt = now_iso()
    store.set_record(rec)
    return f"hypothesis '{name}' recorded as {verdict}"


def _do_lookup_cve(keyword: str = "unauthenticated Jupyter Ray notebook remote code execution") -> str:
    """Call NVD (enrich.lookup_cve) and format the real CVE + CVSS for the exploited vector."""
    from . import enrich
    c = enrich.lookup_cve(keyword)
    score = f"CVSS {c['cvss']} {c.get('severity') or ''}".strip() if c.get("cvss") else "severity n/a"
    return f"{c['id']} ({score}) [{c['source']}] — {c.get('summary', '')} {c.get('url', '')}".strip()


def _do_mining_impact(hours: float = 1.0) -> str:
    """Call CoinGecko (enrich.mining_impact) and format the live $ cost of the stolen GPU compute."""
    from . import enrich
    m = enrich.mining_impact(hours)
    return (f"Monero ${m['xmr_usd_now']} now [{m['source']}]; a Tesla T4 rents at "
            f"${m['t4_usd_per_hour']}/hr, so {m['hours']}h of cryptojacking is ~${m['stolen_compute_usd']} "
            f"of stolen compute — plus the firm's paid GPU jobs slowed while it ran.")


_RAW = {
    "list_pods": _do_list_pods,
    "describe_pod": _do_describe_pod,
    "get_pod_logs": _do_get_pod_logs,
    "gpu_status": _do_gpu_status,
    "get_runbook": _do_get_runbook,
    "lookup_cve": _do_lookup_cve,
    "mining_impact": _do_mining_impact,
    "delete_pod": _do_delete_pod,
    "quarantine_pod": _do_quarantine_pod,
    "delete_cronjob": _do_delete_cronjob,
    "revoke_service_account": _do_revoke_service_account,
    "cordon_node": _do_cordon_node,
    "update_scope": _do_update_scope,
    "update_incident_record": _do_update_incident_record,
    "record_hypothesis": _do_record_hypothesis,
}

_TOOL_TARGET = lambda args: args.get("name") or args.get("asset") or args.get("namespace") or ""


def _summarize_call(tool: str, args: dict) -> str:
    inner = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{tool}({inner})"


def _approval_sig(tool: str, args: dict) -> tuple:
    """Identity of a proposed action, for de-duping approvals: same tool + same target is the
    same request. revoke_service_account takes no args, so its signature is just the tool name —
    which is exactly why two Advisor runs would otherwise file it twice."""
    return (tool, _TOOL_TARGET(args) or json.dumps(args or {}, sort_keys=True))


def _pending_summary() -> str:
    """One line listing actions already awaiting a human, so the Advisor can SEE current decisions
    and not re-propose them. Fed into the Advisor's context at the start of its run."""
    if not pending_actions:
        return "No actions are currently awaiting human approval."
    items = "; ".join(f"{_summarize_call(t, a)} ({aid})" for aid, (t, a, _) in pending_actions.items())
    return f"Already awaiting human approval — do NOT propose these again: {items}."


def _hypotheses_summary() -> str:
    """The hypotheses the Investigator filed, name + verdict + evidence, for the Advisor's context.
    This is passing the pipeline's state along, not deciding anything for the Advisor — it still
    maps each name to its runbook and chooses the containment itself."""
    rec = store.record
    if not rec or not rec.hypotheses:
        return "Filed hypotheses: (none)"
    items = "; ".join(
        f"{h.name} = {h.verdict}" + (f" — {h.evidence}" if h.evidence else "")
        for h in rec.hypotheses
    )
    return f"Filed hypotheses: {items}"


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
    try:
        result = _RAW[tool](**args)
    except AgentIdentityUnavailable as e:
        # Fail closed: never retry with the admin identity. The approval stays consumed
        # and the timeline records why the executor could not act.
        result = f"refused: {e}"
    store.add_timeline(
        kind="agent",
        actor=_AGENT_NAME[EXECUTOR],
        text=f"Executed approved action: {_summarize_call(tool, args)} — {result}",
        severity="high",
        autonomy={"mode": "needs-approval", "reason": "approved by " + by, "approvalId": approval_id},
        tool=_summarize_call(tool, args),
        target=_TOOL_TARGET(args),
        tool_args=args,
        tool_result=result,
        pod_logs=pod_logs,
        agent=EXECUTOR,
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
        # Idempotent approvals: if an identical action is already awaiting a human, do NOT file a
        # second request — point the agent at the existing one. The Advisor can run more than once
        # per incident (one run per detection cycle), and revoke_service_account takes no args, so
        # without this it gets proposed once per run and the operator sees duplicate cards.
        sig = _approval_sig(tool, args)
        dup = next((aid for aid, (t, a, _) in pending_actions.items() if _approval_sig(t, a) == sig), None)
        if dup:
            _log_decision({"tool": tool, "args": args, "mode": "needs-approval",
                           "decision": "duplicate-suppressed", "approvalId": dup})
            return (f"POLICY: '{tool}' is ALREADY pending human approval ({dup}). A second request "
                    f"was NOT created. Do not propose it again; continue with other containment.")
        approval = Approval(
            id=f"ap-{uuid.uuid4().hex[:8]}",
            requestedAt=now_iso(),
            requestedBy=AGENT,
            action=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            rationale=reason,
            policyReason=policy_reason,
            impact=_impact_for(tool, args),
            rank=_runbook_for(tool)["rank"],
            runbookRef=_runbook_for(tool)["runbookRef"],
            risk=_runbook_for(tool)["risk"],
            reversible=_runbook_for(tool)["reversible"],
            status="pending",
        )
        store.upsert_approval(approval)
        pending_actions[approval.id] = (tool, args, reason)
        store.add_timeline(
            kind="agent",
            actor=_AGENT_NAME.get(_current_agent, AGENT),
            text=f"Requesting human approval to {_summarize_call(tool, args)} — {policy_reason}.",
            severity="high",
            autonomy={"mode": "needs-approval", "reason": policy_reason, "approvalId": approval.id},
            tool=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            tool_args=args,
            reasoning=_round_reasoning or None,
            agent=_current_agent,  # the proposing agent (Advisor)
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
    if tool in READ_TOOLS:
        # A look-only lookup: surface it in the agent's trace (traceOnly) so the
        # investigation is visible, but keep it out of the main incident timeline.
        store.add_timeline(
            kind="agent",
            actor=_AGENT_NAME.get(_current_agent, AGENT),
            text=f"Looked up {_summarize_call(tool, args)}",
            severity="info",
            tool=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            tool_args=args,
            tool_result=result,
            reasoning=_round_reasoning or None,
            agent=_current_agent,
            trace_only=True,
        )
    elif tool in ENRICH_TOOLS:
        # An external-service lookup (NVD / CoinGecko): shown in the main timeline, because
        # pulling in a real CVE or dollar impact is a headline part of the investigation.
        store.add_timeline(
            kind="agent",
            actor=_AGENT_NAME.get(_current_agent, AGENT),
            text=f"External lookup ({tool}) — {result}",
            severity="info",
            tool=_summarize_call(tool, args),
            tool_args=args,
            tool_result=result,
            reasoning=_round_reasoning or None,
            agent=_current_agent,
        )
    elif tool == "record_hypothesis" and not result.startswith("ERROR"):
        # A hypothesis is the visible reasoning chain: on the main timeline AND the trace,
        # tagged so the console highlights it. Paperwork, so not an "action taken".
        verdict = args.get("verdict", "").replace("_", " ")
        store.add_timeline(
            kind="agent",
            actor=_AGENT_NAME.get(_current_agent, AGENT),
            text=f"Hypothesis — {args.get('name', '').strip().lower()}: {verdict}. {args.get('evidence', '')}".strip(),
            severity="info",
            reasoning=_round_reasoning or None,
            agent=_current_agent,
            hypothesis={"name": args.get("name", "").strip().lower(), "verdict": args.get("verdict"),
                        "evidence": args.get("evidence", "")},
        )
    else:
        # A mutating tool that ran without approval: the Executor identity did the write.
        is_write = tool not in RECORD_TOOLS
        store.add_timeline(
            kind="agent",
            actor=_AGENT_NAME[EXECUTOR] if is_write else _AGENT_NAME.get(_current_agent, AGENT),
            text=f"{_summarize_call(tool, args)} — {result}",
            severity="medium",
            autonomy={"mode": "autonomous", "reason": reason},
            tool=_summarize_call(tool, args),
            target=_TOOL_TARGET(args),
            tool_args=args,
            tool_result=result,
            reasoning=_round_reasoning or None,
            pod_logs=pod_logs,
            agent=EXECUTOR if is_write else _current_agent,
        )
        if is_write:  # paperwork (scope / record edits) isn't a response action
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
        fn(
            "get_runbook",
            "Read the firm's incident runbook for a scenario: how to confirm it, the ordered containment "
            "steps (with their RB-0x action ids and which need a human), what to record, and when it is done. "
            "Use 'containment-actions' for the individual actions.",
            {"scenario": {"type": "string", "enum": sorted(runbooks())}}, ["scenario"],
        ),
        fn(
            "lookup_cve",
            "Look up the REAL CVE for the exploited vector in NVD (returns id, CVSS score, summary). "
            "Describe the exploit in plain words, e.g. 'unauthenticated Jupyter/Ray notebook remote code execution'.",
            {"keyword": {"type": "string"}}, [],
        ),
        fn(
            "mining_impact",
            "Get the live Monero price and the $/hour value of the stolen GPU compute, to quantify the attack's real-world cost.",
            {"hours": {"type": "number", "description": "hours the GPU was pinned; default 1"}}, [],
        ),
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
                "summary": {"type": "string", "description": "2-3 sentences: what happened"},
                "impact": {"type": "string", "description": "business impact: data lost, $ compute stolen, clients affected"},
                "rootCause": {"type": "string", "description": "how the attacker got in (the exploited weakness)"},
            }}},
            ["fields"],
        ),
        fn(
            "record_hypothesis",
            "File one hypothesis you are weighing, with its verdict and the evidence behind it. Call it "
            "when you form a hypothesis (verdict 'possible') and AGAIN whenever a tool result changes it "
            "('likely', 'confirmed' or 'ruled_out'). Same name = update, not a duplicate.",
            {"name": {"type": "string", "description": "exactly one scenario id: 'cryptojacking', 'data-exfiltration', 'persistence', 'egress-flood'"},
             "verdict": {"type": "string", "enum": sorted(_VERDICTS)},
             "evidence": {"type": "string", "description": "the concrete tool output that supports this verdict, one sentence"}},
            ["name", "verdict", "evidence"],
        ),
        fn(
            "consult_investigator",
            "Ask the Investigator agent a direct follow-up question (they re-check the live cluster "
            "read-only and answer). Use when you need a detail their handoff did not cover before you act.",
            {"question": {"type": "string"}},
            ["question"],
        ),
    ]


# Shared context every agent gets up front: the scenario, so each prompt only has to
# describe that agent's own job.
_SCENARIO = (
    "You defend a law firm's GPU cluster, built on NVIDIA Nemotron. An attacker has compromised "
    "workloads in the 'lawfirm' Kubernetes namespace using a stolen service-account token. You are "
    "one agent in a three-stage response team (Triage -> Investigator -> Advisor); do only your own "
    "stage's job and hand off cleanly.\n\n"
    "ATTACK SIGNATURES — classify by the DISCRIMINATING signal, not by the pod being unowned:\n"
    "| id | Strong signals (any one is enough to call it likely) | NOT this if |\n"
    "|----|------|------|\n"
    "| cryptojacking | unowned pod requesting `nvidia.com/gpu`; GPU pinned ~100%; logs with `[matmul]`, `xmrig`, `stratum` | pod has no GPU request |\n"
    "| data-exfiltration | non-model-server pod mounting the `model-weights` PVC; `curl`/`PUT`/upload in its command; drop-site evidence | nothing mounts the weights |\n"
    "| persistence | a CronJob not on the allowlist; pods named `<cronjob>-<digits>-xxxxx`; a pod that reappears after deletion | no non-allowlisted CronJob |\n"
    "| egress-flood | unowned pod with no GPU and no PVC; logs with `EGRESS-FLOOD`, connection counters, one external `target=host:port` | — |\n"
    "| identity-compromise | always present alongside the above: attacker objects were created with the notebook's service account (root cause) | — |\n\n"
    "An unowned pod is NOT evidence of any one scenario by itself — every attack creates one. "
    "Classify by the discriminating signal (GPU request, weights mount, CronJob, flood logs). "
    "Read the pod (describe + logs) before you name a category. A completed pod (phase Succeeded) "
    "still has readable logs — read them.\n\n"
)

# Tool subsets per stage. Triage and the Investigator only look + update our own paperwork;
# ONLY the Advisor gets the mutating tools, so the approve/executor gate lives in one place.
_TRIAGE_TOOLS = READ_TOOLS | {"update_incident_record"}
_INVESTIGATOR_TOOLS = READ_TOOLS | ENRICH_TOOLS | {"update_scope", "record_hypothesis"}  # forensics also enriches via NVD / price APIs
_ADVISOR_TOOLS = set(_RAW) | {"consult_investigator"}  # every cluster tool + the two-way consult

TRIAGE_PROMPT = _SCENARIO + (
    "You are TRIAGE, the first responder. Size up the incident fast with the read tools, then set "
    "the severity, phase and categories on the incident record (call update_incident_record). Do "
    "NOT contain anything and do not touch scope — that is the Investigator's and Advisor's job.\n\n"
    "CATEGORIES: do NOT set categories until you have run describe_pod AND get_pod_logs on each "
    "unowned pod. Pick categories from the ATTACK SIGNATURES table ids — cryptojacking, "
    "data-exfiltration, persistence, egress-flood — plus 'unauthorized-access'; add only what the "
    "evidence you actually read supports (identity-compromise is the root cause, not a workload "
    "category). Never lower severity below 'high' once an unknown GPU pod is present. Allowed "
    "phases include detection and containment.\n\n"
    "Finish with a 2-3 sentence handoff to the Investigator: what you believe happened, which "
    "signature the evidence matches, and exactly what to dig into. Be terse."
)

INVESTIGATOR_PROMPT = _SCENARIO + (
    "You are the INVESTIGATOR (forensics). Do NOT run a fixed read script — YOU decide the workflow. "
    "But you MUST actually investigate: your FIRST action is a tool call (start with list_pods, then "
    "describe_pod and get_pod_logs on the suspicious pod), NEVER prose. Do not state a conclusion or hand "
    "off until you have read the suspicious pod's details and logs with the tools — a hypothesis is not "
    "evidence. Each round, work like a detective:\n\n"
    "1) COMPETING HYPOTHESES: the candidates are exactly the four scenario ids from the ATTACK "
    "SIGNATURES table — cryptojacking, data-exfiltration, persistence, egress-flood. More than one may "
    "be true at once. After your first reads, call record_hypothesis for EACH candidate with verdict "
    "'possible' (or 'ruled_out' if the evidence already excludes it), citing the tool output. Use "
    "those exact ids as the hypothesis names — no other names.\n"
    "2) NEXT DISCRIMINATING TOOL: choose the single next read (list_pods, describe_pod, get_pod_logs, "
    "gpu_status) that best separates the live hypotheses. The next tool must depend on what the last "
    "result showed — never a stock sequence. A completed pod (phase Succeeded) still has readable "
    "logs — read them.\n"
    "3) UPDATE: whenever a result changes a hypothesis, call record_hypothesis again with the new "
    "verdict ('likely', 'confirmed' or 'ruled_out') and the evidence. Before you hand off, EVERY "
    "candidate must have a final verdict — ruling one out with its 'NOT this if' evidence from the "
    "table is expected and good. Branch on the discriminating signal:\n"
    "   - The pod requests nvidia.com/gpu and the GPU is pinned -> CRYPTOJACKING branch: read its logs "
    "     for miner strings ([matmul], xmrig, stratum) and size the impact.\n"
    "   - A non-model-server pod mounts the model-weights PVC, or its command curls/PUTs to a drop "
    "     site -> EXFIL branch: find the destination and the bytes sent.\n"
    "   - A non-allowlisted CronJob, or a pod that reappears after deletion -> PERSISTENCE branch: "
    "     record the schedule, command, and the pods/jobs it owns.\n"
    "   - An unowned pod with no GPU and no PVC whose logs show EGRESS-FLOOD / connection counters to "
    "     one external target=host:port -> EGRESS-FLOOD branch: record the target and duration.\n"
    "4) SCOPE: record each resolved branch with update_scope, using exactly the asset ids model-weights, "
    "training, notebook, node and a status of clean|investigating|exfiltrated|encrypted|contained. Put "
    "the evidence in the note.\n\n"
    "Everything relevant is in the 'lawfirm' namespace — the tools already default there, so do not "
    "inspect other namespaces. You have a limited number of tool rounds: be decisive, batch your "
    "lookups, and do not re-check something you already saw.\n\n"
    "ENRICH: call lookup_cve for every incident — it identifies the REAL CVE for the exploited vector "
    "(the exposed, unauthenticated notebook/Ray dashboard — the ShadowRay bug). Call mining_impact ONLY "
    "when cryptojacking is confirmed or likely; never call it for a pure egress-flood, exfiltration or "
    "persistence incident. Include the CVE id + CVSS in your handoff, and the $ impact only if you "
    "sized mining.\n\n"
    "Do NOT contain anything — no deleting, quarantining or revoking.\n\n"
    "Finish with a handoff to the Advisor. Its FIRST line must be exactly `CONFIRMED: <ids>` — the "
    "comma-separated hypothesis ids with verdict confirmed or likely, plus identity-compromise (the "
    "attacker objects were created with the notebook's service account), e.g. `CONFIRMED: egress-flood, "
    "identity-compromise`. Then, terse: the evidence per confirmed hypothesis, the ruled-out list (one "
    "clause each), the confirmed scope, the CVE, and the containment actions needed. Use the table ids "
    "as the names so the Advisor can map each hypothesis to its runbook."
)

# Used when the Advisor asks the Investigator a mid-response follow-up (the two-way exchange).
CONSULT_PROMPT = _SCENARIO + (
    "You are the INVESTIGATOR. The Advisor has paused to ask you a direct follow-up question. "
    "Check the live cluster with the read tools, then answer in 1-3 sentences. Do not contain "
    "anything and do not hand off — just answer the question you were asked."
)

ADVISOR_PROMPT = _SCENARIO + (
    "You are the ADVISOR, the containment lead. Triage has classified the incident and the "
    "Investigator has mapped the scope (both are in your context); the filed hypotheses with their "
    "verdicts are listed in your context too.\n\n"
    "RUNBOOKS FIRST: in your FIRST round, call get_runbook for EVERY hypothesis with verdict "
    "confirmed or likely, plus identity-compromise — and nothing for the ruled-out ones. Do not "
    "contain anything in round 1; the reads are instant and batched. Map each hypothesis name to the "
    "runbook with the same id, and from round 2 follow each runbook's Contain order. Name the "
    "runbooks you followed in your final summary.\n\n"
    "CONTAINMENT: quarantine and then delete the unknown attacker pod(s) (owner=none) for the "
    "confirmed scenario — stop the bleeding; delete a non-allowlisted CronJob BEFORE the pods it "
    "spawns; then handle identity. Never delete or disrupt pods owned by 'law-firm' or 'platform'.\n\n"
    "You MAY call consult_investigator(question) AT MOST ONCE, and only if you genuinely cannot "
    "act without a detail their handoff did not cover. Do not use it to re-ask what they already "
    "told you, and never consult twice — contain instead.\n\n"
    "AUTONOMY POLICY (the backend enforces this; respect it): you may act autonomously to delete "
    "UNKNOWN pods (no owner label), quarantine pods, and delete non-allowlisted cronjobs. Actions "
    "that touch legitimate work — revoke_service_account, cordon_node, or deleting an OWNED pod — "
    "require human approval; request them when warranted but do not expect them to run immediately. "
    "Never delete or disrupt pods owned by 'law-firm' or 'platform'.\n\n"
    "ROOT CAUSE: deleting the attacker's objects is not enough while the stolen token still works. "
    "Once you have contained the attacker's pods, CALL revoke_service_account (it routes to a human "
    "for approval; that is expected). Do not just list it as a next step. Advance the phase with "
    "update_incident_record (containment -> eradication) and list next steps. Record the CVE the "
    "Investigator found as the incident `vector` via update_incident_record (e.g. 'CVE-2023-48022 — "
    "unauthenticated notebook RCE'). In that same update, fill the record for the firm's partners: "
    "`summary` (2-3 sentences, what happened), `impact` (the business impact APPROPRIATE TO THE "
    "SCENARIO: compute $ for cryptojacking, what left and how big for exfiltration, target and "
    "duration for a flood), `rootCause` (the exploited weakness + the stolen token), and `nextSteps` "
    "(at most 4, the remaining human work). When containment is done, stop calling tools and give a "
    "one-paragraph summary that states the CVE, the runbooks you followed, and that "
    "scenario-appropriate impact."
)


# Tool-call budget per agent (the force-answer round is the last of these).
_ROUNDS = {TRIAGE: 6, INVESTIGATOR: 8, ADVISOR: 8}

# How the policy gate treats each tool, in words, for the console's agent "Setup" tab.
# The real decision is classify(); this only labels it for people.
_TOOL_POLICY = {
    **{t: "autonomous · read-only" for t in READ_TOOLS},
    **{t: "autonomous · incident paperwork" for t in RECORD_TOOLS},
    **{t: "autonomous · external lookup" for t in ENRICH_TOOLS},
    "quarantine_pod": "autonomous · reversible, attacker only",
    "delete_pod": "autonomous for unknown pods · human approval for owned pods",
    "delete_cronjob": "autonomous unless allowlisted · then human approval",
    "revoke_service_account": "always needs human approval",
    "cordon_node": "always needs human approval",
    "consult_investigator": "agent-to-agent · once per incident",
}


def agent_specs() -> list[dict]:
    """What each reasoning agent actually runs with — model, system prompt, tool budget and the
    exact tool schemas it is offered — read from the same constants run_agent uses, so the
    console shows the real configuration rather than a description of it."""
    schemas = {t["function"]["name"]: t["function"] for t in _tool_schemas()}
    roles = [
        (TRIAGE, config.NEMOTRON_FAST_MODEL, TRIAGE_PROMPT, _TRIAGE_TOOLS),
        (INVESTIGATOR, config.NEMOTRON_FAST_MODEL, INVESTIGATOR_PROMPT, _INVESTIGATOR_TOOLS),
        (ADVISOR, config.NEMOTRON_MODEL, ADVISOR_PROMPT, _ADVISOR_TOOLS),
    ]
    return [
        {
            "id": role, "name": _AGENT_NAME[role], "model": model, "rounds": _ROUNDS[role],
            "systemPrompt": prompt,
            "tools": [
                {**schemas[n], "policy": _TOOL_POLICY.get(n, "needs human approval"),
                 "implementation": inspect.getsource(_RAW.get(n, _consult)),
                 "runbookRef": _RUNBOOK[n]["runbookRef"] if n in _RUNBOOK else None}
                for n in sorted(allowed) if n in schemas
            ],
        }
        for role, model, prompt, allowed in roles
    ]


def nemotron_configured() -> bool:
    return config.nvidia_api_key() is not None


def _client():
    from openai import OpenAI

    return OpenAI(base_url=config.NVIDIA_BASE_URL, api_key=config.nvidia_api_key())


def _handoff(frm: str, to: str, summary: str) -> None:
    """Log one agent passing the incident to the next — the visible 'agents talk to each
    other' moment. The short text is the edge; the full summary rides in `reasoning` so the
    console can expand it under the handing-off agent."""
    store.add_timeline(
        kind="agent", actor=_AGENT_NAME[frm], agent=frm, severity="info",
        text=f"Handing off to {_AGENT_NAME[to].split(' ')[0]}.",
        reasoning=summary or None,
    )


def _consult(oai, question: str) -> str:
    """The Advisor asks the Investigator a follow-up — a real two-way exchange, logged both
    directions. Runs a short read-only Investigator query and returns its answer to the Advisor.
    _run_role logs the Investigator's reads + answer under agent=investigator; we add the
    Advisor's question before it so the back-and-forth reads clearly in the timeline."""
    global _current_agent
    store.add_timeline(
        kind="agent", actor=_AGENT_NAME[ADVISOR], agent=ADVISOR, severity="info",
        text=f"Asks the Investigator: {question}",
    )
    saved = _current_agent
    answer = _run_role(
        oai, role=INVESTIGATOR, model=config.NEMOTRON_FAST_MODEL, system_prompt=CONSULT_PROMPT,
        allowed=READ_TOOLS, rounds=4,
        context=f"The Advisor asks: {question}\n\nCurrent lawfirm pods:\n{_do_list_pods()}\n\nAnswer concisely.",
    )
    _current_agent = saved  # back to the Advisor, which is still mid-loop
    return answer or "(the Investigator found nothing further)"


def _run_role(oai, *, role: str, model: str, system_prompt: str,
              allowed: set[str], context: str, rounds: int = 6,
              require_tool: str | None = None) -> str:
    """Run ONE agent as a Nemotron tool-loop to completion and return its final text (the
    handoff to the next stage). Same loop mechanics for all three; the role differs only in
    its prompt, which tools it may call, and which model runs it.

    The loop: hand the model its prompt + context + allowed tools; each round it either
    gives final text (done) or asks for tool calls, which _dispatch runs under the policy
    gate before we feed results back. Blocking by design."""
    global _current_agent, _round_reasoning
    _current_agent = role
    name = _AGENT_NAME[role]
    tools = [t for t in _tool_schemas() if t["function"]["name"] in allowed]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context},
    ]
    final = ""
    consults = 0  # the Advisor may consult the Investigator at most once (keeps it from looping)
    called: set[str] = set()  # tool names this agent actually used, for require_tool
    nudged = False
    for _round in range(rounds):
        # On the LAST round, withhold the tools and tell the model to wrap up. A reasoning model
        # left with tools will keep calling them until the budget runs out and never writes a
        # final answer — the old "reached its step limit" dead-end. Forcing a tool-free final
        # round guarantees a real terminal state: the next stage always gets a handoff, and the
        # Advisor always produces its containment summary.
        last = _round == rounds - 1
        if last:
            messages.append({"role": "user", "content": (
                "You are out of tool budget — do NOT call any tools. Give your final answer now: "
                "your handoff to the next stage, or (if you are the Advisor) a one-paragraph "
                "containment summary of what you did and what still needs a human.")})
        try:
            resp = oai.chat.completions.create(
                model=model, messages=messages,
                tools=None if last else tools,
                temperature=0, max_tokens=4096,  # temp 0: same incident -> same response, every run
            )
        except Exception as e:  # noqa: BLE001
            store.add_timeline(kind="system", actor="System",
                               text=f"{name} call failed: {e}", severity="medium")
            break
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        # Carry this round's real model reasoning onto the actions it triggers. Some Nemotron
        # deployments surface it as reasoning_content rather than content.
        _round_reasoning = (msg.content or "").strip() or (getattr(msg, "reasoning_content", "") or "").strip()
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ] or None,
        })
        if not tool_calls and require_tool and require_tool not in called and not last and not nudged:
            # The agent tried to finish without the tool its job hinges on (the Investigator's
            # record_hypothesis). One nudge, then accept whatever it does — never a loop.
            nudged = True
            messages.append({"role": "user", "content": (
                f"You have not called {require_tool} yet. Call it now for each hypothesis, with the "
                "evidence you found, before you hand off.")})
            continue
        if not tool_calls:  # the model is done (or was forced to wrap up) — this is its final text
            final = (msg.content or "").strip() or _round_reasoning
            if final:
                store.add_timeline(kind="agent", actor=name, agent=role, text=final, severity="info")
            break
        for tc in tool_calls:
            fname = tc.function.name
            called.add(fname)
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            # Enforce the per-agent tool scope in CODE, not just by what we offered the
            # model: a prompt-injected or confused agent (e.g. Triage) cannot reach another
            # stage's mutating tools. This is the pipeline analogue of classify() — the model
            # proposes, the backend decides. Without it, `allowed` would be advisory only.
            if fname == "consult_investigator" and fname in allowed:
                if consults >= 1:
                    # One consult is the collaboration beat; more is the Advisor stalling instead
                    # of containing. Refuse further consults and push it to act.
                    result = ("Already consulted the Investigator once this incident. Do not consult "
                              "again — act on what you know and contain now.")
                else:
                    consults += 1
                    result = _consult(oai, (args.get("question") or "").strip() or "What should I double-check?")
            elif fname not in allowed:
                result = f"error: tool '{fname}' is not permitted for the {role} agent"
                store.add_timeline(
                    kind="system", actor="System", agent=role, severity="medium",
                    text=f"Blocked {fname}() — outside the {role} agent's tool scope.",
                )
            else:
                result = _dispatch(fname, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:2000]})
    _round_reasoning = ""
    return final


def run_agent(trigger: str) -> None:
    """Drive the three-agent pipeline once, in response to a detection trigger:
    Triage classifies -> Investigator maps scope -> Advisor contains. Each stage's output
    is logged AND threaded into the next stage's context (the handoff). The Advisor is the
    only stage with mutating tools, so the policy gate + approvals are unchanged."""
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
        # Fail closed before spending model calls: both scoped identities must be usable.
        # (Constructing the clients only mints tokens; it performs no cluster write.)
        agent_readonly_core()
        executor_core()
    except AgentIdentityUnavailable as e:
        store.add_timeline(
            kind="system", actor="System", severity="high",
            text=f"Agent identity unavailable — pipeline paused (failing closed, not using admin): {e}",
        )
        return

    try:
        oai = _client()
    except Exception as e:  # noqa: BLE001
        store.add_timeline(kind="system", actor="System",
                           text=f"Nemotron client error: {e}", severity="medium")
        return

    base = (
        f"Detection trigger: {trigger}\n\n"
        f"Current lawfirm pods:\n{_do_list_pods()}\n\n"
        f"GPU: {_do_gpu_status()}\n"
    )

    # 1) Triage — fast model, classify only.
    triage = _run_role(
        oai, role=TRIAGE, model=config.NEMOTRON_FAST_MODEL, system_prompt=TRIAGE_PROMPT,
        allowed=_TRIAGE_TOOLS, rounds=_ROUNDS[TRIAGE], context=base + "\nClassify this incident, then hand off to the Investigator.",
    )
    _handoff(TRIAGE, INVESTIGATOR, triage)

    # 2) Investigator — fast model, scope only. Hypothesis-driven: its next tool depends on
    #    what the last result showed, and each round's hypothesis state is surfaced in its trace.
    inv = _run_role(
        oai, role=INVESTIGATOR, model=config.NEMOTRON_FAST_MODEL, system_prompt=INVESTIGATOR_PROMPT,
        allowed=_INVESTIGATOR_TOOLS, rounds=_ROUNDS[INVESTIGATOR],  # scope 4 assets + CVE + mining impact needs the room
        require_tool="record_hypothesis",
        context=base + f"\nTriage assessment:\n{triage or '(none)'}\n\nForm your hypotheses, decide the "
        "next discriminating read each round, then hand off to the Advisor.",
    )
    _handoff(INVESTIGATOR, ADVISOR, inv)

    # 3) Advisor — heavy model, the only stage that contains. It sees what is already awaiting a
    #    human so it does not re-propose a decision that is already on the operator's queue.
    advisor_summary = _run_role(
        oai, role=ADVISOR, model=config.NEMOTRON_MODEL, system_prompt=ADVISOR_PROMPT,
        allowed=_ADVISOR_TOOLS, rounds=_ROUNDS[ADVISOR],
        context=base + f"\nTriage assessment:\n{triage or '(none)'}\n\n"
        f"Investigator findings:\n{inv or '(none)'}\n\n{_hypotheses_summary()}\n\n{_pending_summary()}\n\n"
        "Propose and execute the ranked remediation now.",
    )
    # The record's summary must never be blank: if the Advisor skipped filling it, its own
    # closing paragraph is exactly that summary.
    if advisor_summary and store.record and not store.record.summary:
        _record_merge({"summary": advisor_summary})

    # 4) Verify-and-reconverge — the Advisor checks its own work. Deleting a miner pod is not
    #    enough while a CronJob keeps recreating it, so re-observe the live cluster (read-only)
    #    and, if anything rogue survived, run the Advisor once more against exactly those
    #    residual findings. Bounded to _MAX_VERIFY_PASSES so this can never loop; the background
    #    detection_loop still re-checks every 4 s afterwards. Re-acting goes through the same
    #    classify()/_dispatch gate, and _approval_sig de-dup stops a second revoke card.
    reacted_again = False
    for attempt in range(1, _MAX_VERIFY_PASSES + 1):
        store.add_timeline(
            kind="agent", actor=_AGENT_NAME[ADVISOR], agent=ADVISOR, severity="info",
            text="Verifying containment — re-observing the live cluster…",
        )
        residual = _detect_settled()
        if not residual:
            store.add_timeline(
                kind="agent", actor=_AGENT_NAME[ADVISOR], agent=ADVISOR, severity="info",
                text=("Re-contained: rogue work respawned after the first pass; removed again. "
                      "Confirmed: all rogue workloads cleared." if reacted_again
                      else "Confirmed: all rogue workloads cleared."),
            )
            break
        detail = "; ".join(text for _, text in residual)
        if attempt == _MAX_VERIFY_PASSES:
            # Out of in-run passes: hand the residual state to the background detector instead of
            # looping. It escalates anything genuinely new on its next tick.
            store.add_timeline(
                kind="system", actor="Detector", severity="high",
                text=(f"Verify pass {attempt}/{_MAX_VERIFY_PASSES}: rogue state still present — "
                      f"leaving it to the background detector: {detail}"),
            )
            break
        reacted_again = True
        store.add_timeline(
            kind="agent", actor=_AGENT_NAME[ADVISOR], agent=ADVISOR, severity="high",
            text=f"Verification found residual rogue state — re-converging: {detail}",
        )
        # Fresh read of the live cluster for the follow-up: the first pass's `base` is stale.
        verify_base = (
            f"Detection trigger: {trigger}\n\n"
            f"Current lawfirm pods (re-read after your first containment pass):\n{_do_list_pods()}\n\n"
            f"GPU: {_do_gpu_status()}\n"
        )
        _run_role(
            oai, role=ADVISOR, model=config.NEMOTRON_MODEL, system_prompt=ADVISOR_PROMPT,
            allowed=_ADVISOR_TOOLS, rounds=6,
            context=verify_base + f"\nTriage assessment:\n{triage or '(none)'}\n\n"
            f"Investigator findings:\n{inv or '(none)'}\n\n"
            f"{_hypotheses_summary()}\n\n"
            f"Your earlier containment pass ended with:\n{advisor_summary or '(none)'}\n\n"
            f"VERIFY FINDINGS — these rogue objects are STILL present after your first pass:\n{detail}\n\n"
            f"{_pending_summary()}\n\n"
            "Clear these residual findings now: remove what recreates the work (e.g. the CronJob) AND "
            "the objects it already spawned. Do not re-propose an action that is already awaiting a "
            "human. When done, stop calling tools and summarize.",
        )


# ---------------------------------------------------------------------------
# Deterministic detection
# ---------------------------------------------------------------------------
# WHY RULES, NOT AI, FOR DETECTION (for a learner): spotting the attack is pure
# code — fast, cheap, and runs every 4 seconds. It looks for four tell-tale signs
# in the REAL cluster state, each of which a normal law-firm workload would never
# produce: (1) a pod with no owner=law-firm label, (2) a pod other than the model
# server mounting the weights disk, (3) a GPU pinned at 100% by an unowned pod,
# (4) a CronJob nobody put on the allowlist. The expensive AI only wakes up AFTER
# a rule fires — the rules raise the alarm, the agent does the thinking.
_MAX_GRACE = 30  # seconds; a larger terminationGracePeriodSeconds is treated as an attacker hiding


def _terminating_is_settled(obj, now: datetime | None = None) -> bool:
    """True only when a terminating pod/CronJob is genuinely on its way out.

    Fail CLOSED: an attacker can add a finalizer or a huge terminationGracePeriodSeconds
    so the object sits in Terminating while its container keeps running — and the old
    `deletion_timestamp is None` filter made detection blind to it forever. We skip a
    terminating object ONLY if it has no finalizers, a grace period no larger than a
    normal shutdown (_MAX_GRACE), AND its deletion deadline (grace + 30 s slack) has
    not passed. Anything else is evaluated as rogue — the grace period comes from the
    object's own spec, so an inflated value is an attacker keeping a "deleted" pod alive.
    """
    ts = getattr(obj.metadata, "deletion_timestamp", None)
    if ts is None:
        return False
    if getattr(obj.metadata, "finalizers", None):
        return False
    grace = getattr(getattr(obj, "spec", None), "termination_grace_period_seconds", None)
    if grace is None:
        grace = 30
    if grace > _MAX_GRACE:  # attacker-controlled: a real workload never needs this long to stop
        return False
    now = now or datetime.now(timezone.utc)
    return now < ts + timedelta(seconds=grace + 30)


def _selfcheck_terminating() -> None:
    """Runnable, cluster-free check of the fail-closed terminating rule.

    Run with: cd backend && uv run python -m app.defender
    """
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)

    def obj(age: float | None, finalizers=None, grace: int | None = 30):
        return SimpleNamespace(
            metadata=SimpleNamespace(
                deletion_timestamp=None if age is None else now - timedelta(seconds=age),
                finalizers=finalizers,
            ),
            spec=SimpleNamespace(termination_grace_period_seconds=grace),
        )

    assert _terminating_is_settled(obj(0), now), "fresh delete must be skipped"
    assert not _terminating_is_settled(obj(65), now), "past grace+slack must stay rogue"
    assert not _terminating_is_settled(obj(0, finalizers=["example.com/hold"]), now), "finalizer must stay rogue"
    assert not _terminating_is_settled(obj(0, grace=3600), now), "inflated grace period must stay rogue"
    assert not _terminating_is_settled(obj(None), now), "a running pod is not terminating"
    assert _terminating_is_settled(obj(50, grace=None), now), "missing grace defaults to 30 + 30 slack"
    assert not _terminating_is_settled(obj(61, grace=None), now), "default grace deadline is enforced"
    print("terminating-object fail-closed self-check: OK")


def _detect() -> list[tuple[str, str]]:
    """Return list of (dedupe_key, human trigger) findings from real state."""
    findings: list[tuple[str, str]] = []
    core = admin_core()
    try:
        # Skip an object only when it is genuinely leaving: a finalizer or a long grace
        # period can keep a "Terminating" pod running, so those stay visible to detection.
        pods = [
            p for p in core.list_namespaced_pod(config.LAWFIRM_NS).items
            if not _terminating_is_settled(p)
        ]
    except ApiException:
        return findings

    for p in pods:
        name = p.metadata.name
        labels = p.metadata.labels or {}
        owner = labels.get("owner")
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
            # Same fail-closed rule as pods: a CronJob being torn down with no finalizers
            # is not residual persistence; one held by a finalizer is still rogue.
            if _terminating_is_settled(cj):
                continue
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


# Verify-and-reconverge bounds (Spec 06). At most 2 re-observations per run; the background
# detection_loop remains the unbounded 4 s safety net, so the in-run pass never competes with it.
_MAX_VERIFY_PASSES = 2
_VERIFY_SETTLE_ATTEMPTS = 3
_VERIFY_SETTLE_S = 0.4


def _detect_settled() -> list[tuple[str, str]]:
    """Re-observe after containment, giving in-flight deletions a moment to settle.

    A pod deleted with grace 0 can linger in the API for a beat and nvidia-smi can read busy a
    moment after its miner dies. Without a short settle, a simple miner deletion would look like
    residual rogue state and trigger a pointless second Advisor pass. A clean observation wins
    immediately; otherwise we re-poll up to _VERIFY_SETTLE_ATTEMPTS times and return the last read.
    """
    findings = _detect()
    for _ in range(_VERIFY_SETTLE_ATTEMPTS - 1):
        if not findings:
            return findings
        time.sleep(_VERIFY_SETTLE_S)
        findings = _detect()
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


def detection_tick() -> list[tuple[str, str]]:
    """One detection cycle: detect, fold in drop-site exfil evidence, and escalate any
    NEW findings to the agent. Returns the findings escalated this tick. The background
    detection_loop() calls this every 4 s; the WS-C evals harness calls it directly to
    step the defender synchronously."""
    findings = _detect()
    _check_exfil_evidence()
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
        run_agent(trigger)
    return new


async def detection_loop() -> None:
    """Background task: poll for threats, escalate new ones to Nemotron."""
    await asyncio.to_thread(verify_readonly_identity)  # prove the agent's identity is read-only, once at startup
    while True:
        try:
            await asyncio.to_thread(detection_tick)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(4)


def reset_detection_state() -> None:
    _handled.clear()
    pending_actions.clear()


# ---------------------------------------------------------------------------
# Metrics (judges asked for measurable outcomes) — derived from decisions.jsonl
# ---------------------------------------------------------------------------
_CONTAIN_TOOLS = {"delete_pod", "quarantine_pod", "delete_cronjob", "revoke_service_account", "cordon_node"}
_DETECTION_CADENCE_S = 4  # the detection loop polls every 4 s (upper bound on detect latency)


def _read_decisions() -> list[dict]:
    if not config.DECISIONS_LOG.exists():
        return []
    out = []
    for line in config.DECISIONS_LOG.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def metrics() -> dict:
    """Current-incident metrics, computed from the decision log. Everything is scoped to
    decisions made since the incident was detected, so stale runs don't inflate it.

    What the numbers mean (for a learner), all read back from logs/decisions.jsonl:
      * timeToContainSeconds  — detection -> first containment action. The headline "how
        fast did we stop it" number.
      * containmentActions    — how many actions the agent took on its own vs. how many a
        human approved (shows the autonomy policy actually gating things).
      * approvals.meanTimeToApproveSeconds — how long the human took to click approve.
      * gpuHoursSaved         — mining prevented since containment (a rough live estimate).
    These feed the /defender/metrics endpoint and the console's numbers.
    """
    rec = store.record
    detected = _parse_ts(rec.detectedAt) if rec and rec.detectedAt else None
    # A labeled, conservative baseline for a *manual* response (triage + investigate + contain by a
    # human on the CLI). Not a measured number — it's the bar the agent beats. ~15 min.
    _MANUAL_BASELINE_S = 900
    _GPU_USD_PER_HOUR = 0.526  # Tesla T4 on-demand cloud rate (mirrors enrich._T4_USD_PER_HOUR)
    empty = {
        "detectedAt": rec.detectedAt if rec else None, "firstContainedAt": None,
        "timeToContainSeconds": None, "detectionCadenceSeconds": _DETECTION_CADENCE_S,
        "containmentActions": {"autonomous": 0, "approved": 0, "total": 0},
        "approvals": {"total": 0, "meanTimeToApproveSeconds": None}, "gpuHoursSaved": 0.0,
        "dollarsSaved": 0.0, "gpuUsdPerHour": _GPU_USD_PER_HOUR,
        "manualBaselineSeconds": _MANUAL_BASELINE_S, "speedupVsManual": None,
    }
    if detected is None:
        return empty

    decs = [d for d in _read_decisions()
            if (ts := _parse_ts(d.get("ts"))) and ts >= detected]  # this incident only

    contain = [d for d in decs if d.get("tool") in _CONTAIN_TOOLS
               and d.get("decision") in ("executed", "approved")]
    first_contain = _parse_ts(contain[0]["ts"]) if contain else None
    autonomous = sum(1 for d in contain if d.get("mode") == "autonomous")
    approved = sum(1 for d in contain if d.get("decision") == "approved")

    # Pair each approval's pending timestamp with its decision timestamp to time the human.
    pending = {d["approvalId"]: _parse_ts(d["ts"]) for d in decs
               if d.get("decision") == "pending" and d.get("approvalId")}
    waits = [(_parse_ts(d["ts"]) - pending[d["approvalId"]]).total_seconds()
             for d in decs
             if d.get("decision") in ("approved", "denied") and d.get("approvalId") in pending
             and _parse_ts(d["ts"])]
    mean_approve = round(sum(waits) / len(waits), 1) if waits else None

    now = datetime.now(timezone.utc)
    ttc = round((first_contain - detected).total_seconds(), 1) if first_contain else None
    # ponytail: assume the miner pinned ~1 GPU at 100%; every hour since containment is one
    # GPU-hour of mining prevented. Grows live. Upgrade: integrate real utilization over the window.
    gpu_hours_saved = round((now - first_contain).total_seconds() / 3600, 2) if first_contain else 0.0

    speedup = round(_MANUAL_BASELINE_S / ttc, 1) if ttc and ttc > 0 else None
    return {
        "detectedAt": rec.detectedAt,
        "firstContainedAt": contain[0]["ts"] if contain else None,
        "timeToContainSeconds": ttc,
        "detectionCadenceSeconds": _DETECTION_CADENCE_S,
        "containmentActions": {"autonomous": autonomous, "approved": approved, "total": len(contain)},
        "approvals": {"total": len(pending), "meanTimeToApproveSeconds": mean_approve},
        "gpuHoursSaved": gpu_hours_saved,
        "dollarsSaved": round(gpu_hours_saved * _GPU_USD_PER_HOUR, 2),
        "gpuUsdPerHour": _GPU_USD_PER_HOUR,
        "manualBaselineSeconds": _MANUAL_BASELINE_S,
        "speedupVsManual": speedup,
    }


if __name__ == "__main__":
    # Cluster-free self-check for the fail-closed terminating-object rule.
    # Run: cd backend && uv run python -m app.defender
    _selfcheck_terminating()
