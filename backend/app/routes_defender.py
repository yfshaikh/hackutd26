"""WS-A/WS-C: defender metrics + eval results endpoints. Additive router — one include
line in main.py."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from . import defender
from .auth import current_user
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


@router.get("/evals")
def defender_evals(user: User = Depends(current_user)) -> dict:
    """WS-C eval results written by `uv run python -m evals`. Empty dict until a run
    has produced evals/results.json, which the console renders as an empty state."""
    if not _EVALS_RESULTS.exists():
        return {}
    try:
        return json.loads(_EVALS_RESULTS.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
