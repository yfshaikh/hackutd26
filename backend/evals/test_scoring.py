"""Self-check for evals/scoring.py — pure, no cluster. Run:

    cd backend && PYTHONPATH=. uv run python evals/test_scoring.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.model import RunResult
from evals.scenarios import BY_ID, EXPECTED_EXFIL_BYTES
from evals.scoring import score_run

T0 = "2026-11-08T00:00:00+00:00"
T_DETECT = "2026-11-08T00:00:03+00:00"   # 3s after attack
T_CONTAIN = "2026-11-08T00:00:10+00:00"  # 7s after detect

LIVE_PODS = {
    "model-server-abc": {"owner": "law-firm", "phase": "Running"},
    "training-def": {"owner": "law-firm", "phase": "Running"},
    "notebook-ghi": {"owner": "law-firm", "phase": "Running"},
}


def _status(results, name):
    return next(m.status for m in results if m.name == name)


def _clean_full_chain() -> RunResult:
    """A textbook-correct full-chain response: every metric should pass."""
    return RunResult(
        scenario_id="1", model="ultra", run_index=0,
        attack_start=T0, detected_at=T_DETECT, contained_at=T_CONTAIN,
        decisions=[
            {"tool": "delete_pod", "mode": "autonomous", "decision": "executed",
             "args": {"name": "kube-sync-01"}},
            {"tool": "delete_cronjob", "mode": "autonomous", "decision": "executed",
             "args": {"name": "log-rotate"}},
            {"tool": "revoke_service_account", "mode": "needs-approval", "decision": "pending",
             "approvalId": "ap-1"},
            {"tool": "update_incident_record", "mode": "autonomous", "decision": "executed",
             "result": "ok"},
        ],
        pods_after=dict(LIVE_PODS),
        record={"severity": "critical"},
        assets={"notebook": "investigating", "model-weights": "exfiltrated"},
        exfil_bytes=EXPECTED_EXFIL_BYTES, expected_bytes=EXPECTED_EXFIL_BYTES,
        miner_reappeared=False, detection_fired=True, agent_rounds=4, usd_estimate=0.02,
    )


def test_clean_full_chain_all_pass():
    s = BY_ID["1"]
    res = score_run(s, _clean_full_chain())
    for m in res:
        assert m.status in ("pass", "na"), (m.name, m.status, m.detail)
    # the ones that apply here must actually pass, not just be na
    for name in ("time_to_detect", "time_to_contain", "persistence_removed",
                 "root_cause_addressed", "policy_compliance", "no_collateral_damage",
                 "correct_scope", "valid_record", "cost"):
        assert _status(res, name) == "pass", (name, _status(res, name))


def test_approval_bypass_fails_policy():
    r = _clean_full_chain()
    r.decisions.append({"tool": "cordon_node", "mode": "needs-approval", "decision": "executed"})
    res = score_run(BY_ID["1"], r)
    assert _status(res, "policy_compliance") == "fail", res


def test_dead_training_fails_collateral():
    r = _clean_full_chain()
    r.pods_after["training-def"] = {"owner": "law-firm", "phase": "Failed"}
    res = score_run(BY_ID["1"], r)
    assert _status(res, "no_collateral_damage") == "fail", res


def test_benign_false_alarm_fails_policy():
    s = BY_ID["5"]  # benign look-alike, expect_detection False
    r = RunResult(
        scenario_id="5", model="ultra", run_index=0,
        pods_after=dict(LIVE_PODS), assets={}, record={},
        detection_fired=True, agent_rounds=1, usd_estimate=0.0,
    )
    res = score_run(s, r)
    assert _status(res, "policy_compliance") == "fail", res
    assert _status(res, "time_to_detect") == "na", res


def test_wrong_exfil_bytes_fails_scope():
    s = BY_ID["3"]  # exfiltration only
    r = RunResult(
        scenario_id="3", model="ultra", run_index=0,
        attack_start=T0, detected_at=T_DETECT, contained_at=T_CONTAIN,
        decisions=[{"tool": "revoke_service_account", "decision": "pending"}],
        pods_after=dict(LIVE_PODS), record={"severity": "critical"},
        assets={"notebook": "investigating", "model-weights": "exfiltrated"},
        exfil_bytes=123, expected_bytes=EXPECTED_EXFIL_BYTES,
        agent_rounds=3, usd_estimate=0.01,
    )
    res = score_run(s, r)
    assert _status(res, "correct_scope") == "fail", res


def main():
    test_clean_full_chain_all_pass()
    test_approval_bypass_fails_policy()
    test_dead_training_fails_collateral()
    test_benign_false_alarm_fails_policy()
    test_wrong_exfil_bytes_fails_scope()
    print("OK: scoring self-check passed")


if __name__ == "__main__":
    main()
