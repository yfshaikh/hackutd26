"""WS-B: Winstead incident-dashboard endpoints.

Pure record / scope / roles / chat CRUD. No attack or defender logic lives here;
the console is the only client. Every write is role-gated server-side.

Routes are additive: ``main.py`` includes this router once and keeps its existing
routes untouched. The approval round-trip stays on the existing
``POST /approvals/{id}/approve|deny`` endpoints.

For a newcomer: "CRUD" = Create / Read / Update / Delete — the basic ways to work
with stored records. These endpoints let the console read and edit the incident
write-up (the NIST record), the asset "scope" (what's compromised), the user roles,
and the people-chat. "Role-gated server-side" means the server checks your role via
`Depends(require_roles(...))` before any change — the browser can't talk its way past it.
HTTP verbs map to the action: GET reads, POST creates, PATCH edits part of a record.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import auth, current_user, require_roles
from .hub import store
from .models import (
    Asset,
    IncidentRecord,
    IncidentRecordPatch,
    NotificationDeadline,
    RecordAction,
    RoleInfo,
    ScopePatch,
    SetRoleBody,
    TimelineEntry,
    User,
    now_iso,
)

router = APIRouter()

# Role catalogue for the UI. Keep in sync with console/src/labels.ts.
_ROLES = [
    RoleInfo(id="admin", label="Admin", canApprove=True, canChat=True, canManageUsers=True),
    RoleInfo(id="approver", label="Approver", canApprove=True, canChat=False, canManageUsers=False),
    RoleInfo(id="operator", label="Operator", canApprove=False, canChat=True, canManageUsers=False),
    RoleInfo(id="responder", label="Responder", canApprove=True, canChat=True, canManageUsers=False),
    RoleInfo(id="viewer", label="Viewer", canApprove=False, canChat=False, canManageUsers=False),
]

_EDITORS = ("admin", "responder", "operator")


def _validate_iso(value: str, field: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO-8601 timestamp") from exc


# ---- Incident record ------------------------------------------------------
@router.get("/incident/record", response_model=Optional[IncidentRecord])
def get_record(user: User = Depends(current_user)) -> Optional[IncidentRecord]:
    """The current incident record (null until the defender opens one)."""
    return store.record


@router.patch("/incident/record", response_model=IncidentRecord)
def patch_record(
    body: IncidentRecordPatch,
    user: User = Depends(require_roles(*_EDITORS)),
) -> IncidentRecord:
    """Edit the record: only fields present in the body change; timestamps are
    ISO-validated and list/enum fields can't be nulled. Logs who changed what."""
    record = store.record
    if record is None:
        raise HTTPException(status_code=404, detail="No incident is open yet")

    fields = body.model_dump(exclude_unset=True)
    non_null = {
        "title", "status", "phase", "severity", "categories", "affectedSystems",
        "nextSteps", "evidence", "containmentMeasures", "notifiedParties",
        "notificationDeadlines",
    }
    for key in non_null:
        if key in fields and fields[key] is None:
            raise HTTPException(status_code=400, detail=f"{key} cannot be null")
    for key in ("detectedAt", "notificationDueAt", "closedAt"):
        if fields.get(key):
            _validate_iso(fields[key], key)
    for deadline in fields.get("notificationDeadlines") or []:
        _validate_iso(deadline.get("dueAt", ""), "notificationDeadlines.dueAt")

    for key, value in fields.items():
        if key == "notificationDeadlines":
            record.notificationDeadlines = [NotificationDeadline(**d) for d in value]
        else:
            setattr(record, key, value)

    record.updatedAt = now_iso()
    changed = ", ".join(sorted(fields)) or "no fields"
    record.actionsTaken.append(
        RecordAction(ts=now_iso(), by=user.name, text=f"Updated the incident record ({changed}).")
    )
    store.set_record(record)
    store.add_timeline(
        kind="human",
        actor=user.name,
        text=f"Updated the incident record: {changed}.",
        severity="info",
    )
    return record


# ---- Scope ----------------------------------------------------------------
@router.get("/incident/scope", response_model=list[Asset])
def get_scope(user: User = Depends(current_user)) -> list[Asset]:
    """The assets in scope and their status (clean / investigating / exfiltrated / ...)."""
    return list(store.assets.values())


@router.patch("/incident/scope/{asset_id}", response_model=Asset)
def patch_scope(
    asset_id: str,
    body: ScopePatch,
    user: User = Depends(require_roles(*_EDITORS)),
) -> Asset:
    """Set one asset's scope status (and optional note); mirrored to the timeline + record."""
    asset = store.set_asset_status(asset_id, body.status, body.note)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"No asset {asset_id!r}")

    text = f"Set scope: {asset.name} → {body.status}."
    if body.note:
        text += f" {body.note}"
    store.add_timeline(kind="human", actor=user.name, text=text, severity="info")

    if store.record is not None:
        store.record.actionsTaken.append(
            RecordAction(ts=now_iso(), by=user.name, text=text)
        )
        store.record.updatedAt = now_iso()
        store.set_record(store.record)
    return asset


# ---- People chat ----------------------------------------------------------
@router.get("/messages", response_model=list[TimelineEntry])
def list_messages(user: User = Depends(current_user)) -> list[TimelineEntry]:
    """Person-to-person chat history for the incident (human timeline entries)."""
    return [e for e in store.timeline if e.kind == "human"]


# ---- Roles ----------------------------------------------------------------
@router.get("/roles", response_model=list[RoleInfo])
def list_roles(user: User = Depends(current_user)) -> list[RoleInfo]:
    """The role catalogue (what each role may do) for the UI."""
    return _ROLES


@router.patch("/users/{user_id}/role", response_model=User)
def set_user_role(
    user_id: str,
    body: SetRoleBody,
    user: User = Depends(require_roles("admin")),
) -> User:
    """Admin-only: change a user's role, but you can't demote yourself out of admin."""
    if user_id == user.id and body.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
    return auth.set_role(user_id, body.role)


__all__ = ["router"]
