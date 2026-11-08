"""WS-A/WS-C: defender metrics + eval results endpoints. Additive router — one include
line in main.py.

For a newcomer: an "endpoint" is one URL the backend answers (e.g. GET /defender/metrics).
A FastAPI "router" is just a small bundle of related endpoints kept in its own file;
main.py `include_router`s it so the URLs become live. Keeping them here (instead of in
main.py) is what let this feature be built without touching the rest of the routes.
  - GET /defender/metrics -> how the agent performed on the CURRENT incident (numbers).
  - GET /defender/evals   -> the saved results of the eval suite (runs across scenarios).
Both require a signed-in session (the `Depends(current_user)` below), same as the dashboard.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from . import defender, evals_run
from .auth import current_user, require_roles
from .hub import store
from .models import User

router = APIRouter(prefix="/defender", tags=["defender"])

# evals/results.json lives beside the app package (backend/evals/), written by `python -m evals`.
_EVALS_RESULTS = Path(__file__).resolve().parent.parent / "evals" / "results.json"


@router.get("/metrics")
def defender_metrics(user: User = Depends(current_user)) -> dict:
    """Measurable outcomes for the current incident: time-to-contain, autonomous vs
    approved actions, mean time-to-approve, and GPU-hours of mining prevented.
    Same auth as /snapshot (any signed-in console user)."""
    return defender.metrics()


@router.get("/agents")
def defender_agents(user: User = Depends(current_user)) -> list[dict]:
    """Each reasoning agent's live configuration: model, system prompt, tool budget and tools."""
    return defender.agent_specs()


@router.get("/runbooks")
def defender_runbooks(user: User = Depends(current_user)) -> list[dict]:
    """The incident runbooks the agents read through get_runbook, as {id, body} Markdown."""
    return [{"id": k, "body": v} for k, v in defender.runbooks().items()]


@router.get("/evals")
def defender_evals(user: User = Depends(current_user)) -> dict:
    """WS-C eval results. Empty dict until a run has produced evals/results.json, which the
    console renders as an empty state."""
    if not _EVALS_RESULTS.exists():
        return {}
    try:
        return json.loads(_EVALS_RESULTS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


@router.post("/evals/run")
def run_evals(user: User = Depends(require_roles("admin"))) -> dict:
    """Start the eval suite in the background (configured model, one run per scenario). Returns
    whether it started (False if one is already in flight) plus the live status to poll.

    DESTRUCTIVE: each scenario resets cluster + incident state, so we refuse while an incident is
    open (it would wipe the responders' live incident) and gate the whole thing to admins."""
    if store.record is not None:
        blank = evals_run.status()
        blank["error"] = ("An incident is open. Running evals resets cluster and incident state, "
                          "so resolve or reset the current incident before running the suite.")
        return {"started": False, **blank}
    started = evals_run.start()
    return {"started": started, **evals_run.status()}


@router.get("/evals/status")
def evals_status(user: User = Depends(current_user)) -> dict:
    """Live progress of a UI-triggered eval run; the console polls this until running is false."""
    return evals_run.status()
