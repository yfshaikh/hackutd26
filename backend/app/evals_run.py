"""Run the eval suite from the UI. A background thread drives the WS-C runner, exposes live
progress, and writes evals/results.json (served by GET /defender/evals). Triggered by
POST /defender/evals/run; the console polls GET /defender/evals/status until it finishes.

ponytail: one configured model, one run per scenario — the "run it from the dashboard" case.
Multi-model / multi-run comparisons stay on the CLI (`python -m evals --runs N --models ...`).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

_lock = threading.Lock()
_state: dict = {
    "running": False, "done": 0, "total": 0, "current": None,
    "startedAt": None, "finishedAt": None, "error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict:
    with _lock:
        return dict(_state)


def start() -> bool:
    """Kick off a run in the background. Returns False if one is already in flight."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, done=0, total=0, current=None,
                      startedAt=_now(), finishedAt=None, error=None)
    threading.Thread(target=_run, daemon=True).start()
    return True


def _run() -> None:
    try:
        from app import config
        from evals import report
        from evals.runner import RunConfig, run_scenario
        from evals.scenarios import SCENARIOS

        model = config.NEMOTRON_MODEL
        cfg = RunConfig()
        selected = [s for s in SCENARIOS if s.kind != "reproducibility"]
        with _lock:
            _state["total"] = len(selected)
        runs = []
        for s in selected:
            with _lock:
                _state["current"] = f"{s.id} · {s.name}"
            runs.append(run_scenario(s, model, 0, cfg))
            with _lock:
                _state["done"] += 1
        results = report.build_results(runs, [model], 1, [])
        report.write_results(results)
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state.update(running=False, current=None, finishedAt=_now())
