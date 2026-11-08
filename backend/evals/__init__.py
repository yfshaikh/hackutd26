"""WS-C evals suite.

    cd backend && uv run python -m evals --runs 3 --models ultra,super

Stages: scenarios (data) -> runner (drives the live cluster + agent) -> scoring (pure,
the 9 metrics) -> report (results.json + table). The console reads GET /defender/evals.
"""
from .model import MetricResult, RunResult, Scenario  # noqa: F401
from .runner import run_scenario  # noqa: F401
from .scoring import score_run  # noqa: F401
