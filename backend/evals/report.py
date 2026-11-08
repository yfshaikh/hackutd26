"""WS-C evals — scoring aggregation, results.json, and the console table.

Takes the RunResults the runner produced, scores each with scoring.score_run(), and
builds the results.json the /defender/evals endpoint and the console page consume.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .model import RunResult, Scenario
from .scenarios import BY_ID, SCENARIOS
from .scoring import score_run

RESULTS_PATH = Path(__file__).resolve().parent / "results.json"
METRIC_NAMES = [
    "time_to_detect", "time_to_contain", "persistence_removed", "root_cause_addressed",
    "policy_compliance", "no_collateral_damage", "correct_scope", "valid_record", "cost",
]


def _secs(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


def _run_entry(scenario: Scenario, r: RunResult) -> dict:
    metrics = [{"name": m.name, "status": m.status, "detail": m.detail} for m in score_run(scenario, r)]
    return {
        "scenarioId": scenario.id, "scenarioName": scenario.name, "model": r.model,
        "runIndex": r.run_index, "ok": r.ok, "error": r.error,
        "detectSeconds": _secs(r.attack_start, r.detected_at),
        "containSeconds": _secs(r.detected_at, r.contained_at),
        "agentRounds": r.agent_rounds, "usdEstimate": r.usd_estimate,
        "metrics": metrics,
    }


def _tally(entries: list[dict], pred) -> dict:
    """pass/fail/na counts over the metric results of the entries `pred` selects."""
    by_metric = {m: {"pass": 0, "fail": 0, "na": 0} for m in METRIC_NAMES}
    for e in entries:
        if not pred(e):
            continue
        for m in e["metrics"]:
            if m["name"] in by_metric:
                by_metric[m["name"]][m["status"]] += 1
    return by_metric


def _pass_rate(by_metric: dict) -> float:
    p = sum(c["pass"] for c in by_metric.values())
    f = sum(c["fail"] for c in by_metric.values())
    return round(p / (p + f), 3) if (p + f) else 0.0


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def reproducibility(runs_a: list[RunResult], runs_b: list[RunResult]) -> list[dict]:
    """Scenario 8: for each model, compare the ordered tool sequence of two runs of the
    same base scenario. Identical sequence = reproducible; otherwise report the variance."""
    out = []
    for a, b in zip(runs_a, runs_b):
        tools_a = [d.get("tool") for d in a.decisions if d.get("tool") != "verify_readonly_identity"]
        tools_b = [d.get("tool") for d in b.decisions if d.get("tool") != "verify_readonly_identity"]
        same = tools_a == tools_b
        out.append({
            "model": a.model, "same": same,
            "runA": tools_a, "runB": tools_b,
            "note": "identical decision sequence" if same
                    else f"diverged: {len(tools_a)} vs {len(tools_b)} actions",
        })
    return out


def build_results(runs: list[RunResult], models: list[str], runs_per_scenario: int,
                  repro: list[dict] | None = None) -> dict:
    entries = [_run_entry(BY_ID[r.scenario_id], r) for r in runs]

    by_scenario = {}
    for s in SCENARIOS:
        if s.kind == "reproducibility":
            continue
        bm = _tally(entries, lambda e, sid=s.id: e["scenarioId"] == sid)
        by_scenario[s.id] = {"name": s.name, "passRate": _pass_rate(bm), "byMetric": bm}

    by_model = {}
    for m in models:
        bm = _tally(entries, lambda e, mm=m: e["model"] == mm)
        mruns = [e for e in entries if e["model"] == m]
        by_model[m] = {
            "passRate": _pass_rate(bm),
            "meanDetectSeconds": _mean([e["detectSeconds"] for e in mruns]),
            "meanContainSeconds": _mean([e["containSeconds"] for e in mruns]),
            "runs": len(mruns),
        }

    return {
        "generatedAt": datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "models": models, "runsPerScenario": runs_per_scenario,
        "scenarios": [{"id": s.id, "name": s.name, "kind": s.kind, "description": s.description}
                      for s in SCENARIOS],
        "runs": entries,
        "summary": {"metricNames": METRIC_NAMES, "byScenario": by_scenario, "byModel": by_model,
                    "reproducibility": repro or []},
    }


def write_results(results: dict, path: Path = RESULTS_PATH) -> None:
    path.write_text(json.dumps(results, indent=2))


def print_table(results: dict) -> None:
    """Compact terminal summary: pass-rate per metric per scenario, then model comparison."""
    s = results["summary"]
    short = {"time_to_detect": "detect", "time_to_contain": "contain", "persistence_removed": "persist",
             "root_cause_addressed": "rootcz", "policy_compliance": "policy", "no_collateral_damage": "collat",
             "correct_scope": "scope", "valid_record": "record", "cost": "cost"}
    cols = [short[m] for m in s["metricNames"]]
    print("\nPass rate per metric per scenario (pass/total, '-' = n/a):")
    print("  " + "scenario".ljust(26) + "  ".join(c.ljust(8) for c in cols))
    for sid, row in s["byScenario"].items():
        cells = []
        for m in s["metricNames"]:
            c = row["byMetric"][m]
            tot = c["pass"] + c["fail"]
            cells.append((f"{c['pass']}/{tot}" if tot else "-").ljust(8))
        print("  " + f"{sid} {row['name']}".ljust(26) + "  ".join(cells) + f"  [{row['passRate']:.0%}]")
    print("\nModel comparison:")
    for model, mm in s["byModel"].items():
        print(f"  {model:42}  pass={mm['passRate']:.0%}  detect={mm['meanDetectSeconds']}s  "
              f"contain={mm['meanContainSeconds']}s  runs={mm['runs']}")
    for rep in s.get("reproducibility", []):
        print(f"  reproducibility [{rep['model']}]: {rep['note']}")
