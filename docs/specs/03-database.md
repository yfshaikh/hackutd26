# Spec 03 — Persist past incidents (history database)

**Lane:** C (backend; shares `hub.py` lightly with Spec 04 — run C and D in the same chat, or sequence them)
**Files:** new `backend/app/db.py`, `backend/app/hub.py` (add an archive seam), `backend/app/main.py`
(two read routes), `.gitignore` (ignore the db file).
**Read first:** `backend/app/hub.py` (the in-memory `store`: `record`, `timeline`, `reset_incident_state`,
`set_record`), `backend/app/models.py` (`IncidentRecord`, `TimelineEntry`).

The live store is in-memory and lost on restart. Add a small persistence layer so **resolved** incidents are
kept and can be listed. Keep it minimal — the live store stays the source of truth for the *active* incident;
the DB is **write-on-resolve, read-for-history** only.

## Implementation
- **stdlib `sqlite3`** (no ORM, no SQLAlchemy). DB file at `backend/data/incidents.db` (create `data/` if absent;
  add `backend/data/` to `.gitignore`).
- Schema (one table):
  ```sql
  CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, title TEXT, status TEXT, severity TEXT, vector TEXT,
    detected_at TEXT, resolved_at TEXT, record_json TEXT, timeline_json TEXT, created_at TEXT
  );
  ```
  Store the full `IncidentRecord` as `record_json` and the incident's timeline as `timeline_json`
  (both `model_dump_json`); the flat columns are for listing/filtering.
- **Write seam:** add `store.archive_incident()` in `hub.py` that serializes the current `record` + `timeline`
  and calls `db.archive(...)`. Call it exactly where an incident leaves the live state:
  (a) when `set_record` moves status → `resolved`, and (b) at the top of `reset_incident_state()` **if** a
  record exists (so a reset banks the incident before clearing). Idempotent on `id` (INSERT OR REPLACE).
- **Read routes** in `main.py` (auth: `Depends(current_user)`, same as `/snapshot`):
  - `GET /incidents` → list, newest first, summary fields only (id, title, status, severity, detected_at, resolved_at).
  - `GET /incidents/{id}` → full row (record + timeline parsed back to JSON).
- **Thread-safety:** the detection loop runs in a worker thread. Open a fresh `sqlite3.connect(...)` per operation
  (or guard with a module-level `threading.Lock`); pass `check_same_thread=False` only if you reuse a connection.

## Acceptance
- Resolve or reset an incident → it appears in `GET /incidents` and survives a backend restart.
- `GET /incidents/{id}` returns the full record + timeline.
- The live/active incident flow is unchanged (snapshot, detection, agents all behave as before).
- No secrets in the DB; `backend/data/` is gitignored.

## Gotchas
- `logs/decisions.jsonl` already persists per-tool decisions and feeds `/defender/metrics` — don't duplicate it.
- Don't make the live store read from the DB; history is a separate read path.
- Never read or commit `.env`.
