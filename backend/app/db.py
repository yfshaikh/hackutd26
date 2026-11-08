"""SQLite persistence for past incidents.

The live command center keeps the *active* incident in `hub.Store` (RAM). This module is
the separate history path: when an incident leaves the live state — it is resolved, or a
reset banks it before clearing — `store.archive_incident()` writes one row here, and the
console can later list past incidents through `GET /incidents` without touching the live
store.

Deliberately tiny: stdlib `sqlite3`, one table, no ORM. Each operation opens its own
short-lived connection so calls from the detection worker thread are safe.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from typing import Any, Iterator, Optional

from . import config
from .models import IncidentRecord, TimelineEntry, now_iso

DB_PATH = config.BACKEND_DIR / "data" / "incidents.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY, title TEXT, status TEXT, severity TEXT, vector TEXT,
  detected_at TEXT, resolved_at TEXT, record_json TEXT, timeline_json TEXT, created_at TEXT
)
"""

# db.py can be called from the event-loop thread and from worker threads (the detection
# loop). A module-level lock plus a fresh connection per call keeps it simple and safe.
_LOCK = threading.Lock()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()


def archive(record: IncidentRecord, timeline: list[TimelineEntry]) -> None:
    """Insert/replace one incident's full record + timeline (idempotent on `id`)."""
    record_json = record.model_dump_json()
    timeline_json = json.dumps([entry.model_dump(mode="json") for entry in timeline])
    # A resolved record may carry its own close time; otherwise stamp "now" for resolved
    # incidents and leave it null for an incident banked by a reset while still open.
    resolved_at = record.closedAt or (now_iso() if record.status == "resolved" else None)

    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO incidents "
            "(id, title, status, severity, vector, detected_at, resolved_at, "
            " record_json, timeline_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.title,
                record.status,
                record.severity,
                record.vector,
                record.detectedAt,
                resolved_at,
                record_json,
                timeline_json,
                now_iso(),
            ),
        )


def list_incidents() -> list[dict[str, Any]]:
    """Summary fields only, newest first — what the history list in the console needs."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, status, severity, detected_at, resolved_at "
            "FROM incidents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_incident(incident_id: str) -> Optional[dict[str, Any]]:
    """One full row, with record + timeline parsed back from their JSON columns."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        return None

    incident = dict(row)
    incident["record"] = json.loads(incident.pop("record_json"))
    incident["timeline"] = json.loads(incident.pop("timeline_json"))
    return incident
