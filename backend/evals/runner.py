"""WS-C evals — the runner.

Drives one scenario for real on the cluster, steps the defender synchronously, and
collects a RunResult for the scorer. It runs IN-PROCESS (this process has its own
app.hub.store; it is not the live backend server), so don't run evals while demoing —
both would drive the same cluster.

Flow per run:  reset -> set up the scenario (attack steps / benign pod) -> step the
defender with defender.detection_tick() until contained or a tick budget runs out ->
collect decisions.jsonl slice + cluster/record/scope state.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from app import attacks, cluster, config, defender
from app.hub import store
from app.k8s import ApiException, admin_core

from .model import RunResult, Scenario
from .scenarios import EXPECTED_EXFIL_BYTES

CONTAIN_TOOLS = {"delete_pod", "quarantine_pod", "delete_cronjob", "revoke_service_account", "cordon_node"}
_EVAL_LABEL = "hackutd/eval"  # benign pods we create carry this so reset can remove them
_PER_ROUND_USD = 0.004        # ponytail: flat per-round estimate; swap for real token usage if logged


@dataclass
class RunConfig:
    tick_sleep: float = 3.0     # seconds between detection ticks
    max_ticks: int = 12         # upper bound on detection cycles per run
    settle_ticks: int = 2       # consecutive quiet ticks that count as "done"
    reappear_wait: float = 20.0  # persistence check: seconds to watch for a respawned miner (0 = skip)


def _now_iso() -> str:
    return datetime.now(__import__("datetime").timezone.utc).isoformat()


def _lawfirm_pods() -> dict[str, dict]:
    """name -> {owner, phase, gpu} for every pod in lawfirm right now."""
    out: dict[str, dict] = {}
    try:
        for p in admin_core().list_namespaced_pod(config.LAWFIRM_NS).items:
            labels = p.metadata.labels or {}
            gpu = any("nvidia.com/gpu" in (c.resources.limits or {}) for c in (p.spec.containers or []))
            out[p.metadata.name] = {
                "owner": labels.get("owner"),
                "phase": p.status.phase,
                "gpu": gpu,
            }
    except ApiException:
        pass
    return out


def _rogue_present() -> bool:
    """True if an unowned (attacker) pod is still Running, or a rogue CronJob exists."""
    for name, info in _lawfirm_pods().items():
        if info["owner"] in (None, "", "unknown") and info["phase"] == "Running":
            return True
    try:
        for cj in defender.admin_batch().list_namespaced_cron_job(config.LAWFIRM_NS).items:
            if cj.metadata.name not in config.CRONJOB_ALLOWLIST:
                return True
    except ApiException:
        pass
    return False


def _delete_eval_pods() -> None:
    try:
        pods = admin_core().list_namespaced_pod(config.LAWFIRM_NS, label_selector=f"{_EVAL_LABEL}=benign").items
        for p in pods:
            admin_core().delete_namespaced_pod(p.metadata.name, config.LAWFIRM_NS)
    except ApiException:
        pass


def _create_benign_pod(gpu: bool) -> str:
    """A legitimate, owner-labelled workload the firm launches. A correct defender must
    NOT flag it (it carries owner=law-firm), which is the point of scenarios 5 and 6."""
    name = f"training-extra-{uuid.uuid4().hex[:6]}"
    container = {
        "name": "train", "image": "pytorch/pytorch:2.5.1-cuda12.4",
        "command": ["python", "-c", "import time\nwhile True: time.sleep(5)"],
    }
    if gpu:
        container["resources"] = {"limits": {"nvidia.com/gpu": 1}}
    body = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {"name": name, "labels": {"owner": "law-firm", "app": "training", _EVAL_LABEL: "benign"}},
        "spec": {"restartPolicy": "Never", "containers": [container]},
    }
    admin_core().create_namespaced_pod(config.LAWFIRM_NS, body)
    return name


def _reset() -> None:
    """Clean slate: remove attacker + benign-eval objects, clear incident state, re-seed scope."""
    _delete_eval_pods()
    attacks.reset()
    defender.reset_detection_state()
    store.reset_incident_state()        # clears record, timeline, approvals, assets; relocks steps
    for a in cluster.seed_assets():     # seed_assets() only RETURNS the list, so upsert each back in
        store.upsert_asset(a)
    time.sleep(2)  # let deletions settle on the cluster


def _decisions_since(start_iso: str) -> list[dict]:
    start = datetime.fromisoformat(start_iso)
    out = []
    for d in defender._read_decisions():
        ts = d.get("ts")
        try:
            if ts and datetime.fromisoformat(ts) >= start:
                out.append(d)
        except (ValueError, TypeError):
            continue
    return out


def run_scenario(scenario: Scenario, model: str, run_index: int, cfg: RunConfig | None = None) -> RunResult:
    """Run one scenario once against `model` and return a scored-ready RunResult."""
    cfg = cfg or RunConfig()
    config.NEMOTRON_MODEL = model  # run_agent reads this at call time → model comparison
    r = RunResult(scenario_id=scenario.id, model=model, run_index=run_index,
                  expected_bytes=EXPECTED_EXFIL_BYTES if scenario.expect_exfil else 0)
    try:
        _reset()
        run_start = _now_iso()

        # --- set up the scenario -------------------------------------------
        if scenario.benign_pod:
            _create_benign_pod(gpu=scenario.benign_gpu)
        r.attack_start = _now_iso()
        for step in scenario.steps:
            attacks.run_step(step)
        if scenario.inject_prompt:
            attacks.plant_prompt_injection()

        # --- step the defender until contained or the tick budget runs out -
        quiet = 0
        for _ in range(cfg.max_ticks):
            new = defender.detection_tick()
            if new:
                r.detection_fired = True
                quiet = 0
            else:
                quiet += 1
            if not _rogue_present() and quiet >= cfg.settle_ticks:
                break
            time.sleep(cfg.tick_sleep)

        # --- persistence: did the miner come back? -------------------------
        if scenario.expect_persistence and cfg.reappear_wait > 0:
            before = set(_lawfirm_pods())
            time.sleep(cfg.reappear_wait)
            defender.detection_tick()  # a respawn would be caught and re-contained
            after = _lawfirm_pods()
            r.miner_reappeared = any(
                n not in before and info["owner"] in (None, "", "unknown") and info["gpu"]
                for n, info in after.items()
            )

        # --- collect --------------------------------------------------------
        r.decisions = _decisions_since(run_start)
        r.detected_at = store.record.detectedAt if store.record else None
        contain = [d for d in r.decisions if d.get("tool") in CONTAIN_TOOLS
                   and d.get("decision") in ("executed", "approved")]
        r.contained_at = contain[0]["ts"] if contain else None
        r.pods_after = _lawfirm_pods()
        r.record = store.record.model_dump() if store.record else {}
        r.assets = {a_id: a.status for a_id, a in store.assets.items()}
        weights = store.assets.get("model-weights")
        if weights and weights.status == "exfiltrated" and weights.note:
            r.exfil_bytes = next((int(x) for x in weights.note.split() if x.isdigit()), 0)
        r.agent_rounds = sum(1 for d in r.decisions
                             if d.get("tool") != "verify_readonly_identity"
                             and d.get("decision") in ("executed", "approved", "pending"))
        r.usd_estimate = round(r.agent_rounds * _PER_ROUND_USD, 3)
    except Exception as e:  # noqa: BLE001  — one bad run must not kill the suite
        r.ok = False
        r.error = f"{type(e).__name__}: {e}"
    return r
