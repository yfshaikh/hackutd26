"""WS-A: defender metrics endpoint. Additive router — one include line in main.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from . import defender
from .auth import current_user
from .models import User

router = APIRouter(prefix="/defender", tags=["defender"])


@router.get("/metrics")
def defender_metrics(user: User = Depends(current_user)) -> dict:
    """Measurable outcomes for the current incident: time-to-contain, autonomous vs
    approved actions, mean time-to-approve, and GPU-hours of mining prevented.
    Same auth as /snapshot (any signed-in console user)."""
    return defender.metrics()
