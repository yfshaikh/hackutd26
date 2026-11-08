# WS-B spec — full Winstead incident dashboard (UI)

**Hand this whole file to the implementer. It is self-contained.**

## Authorization & context (read first)

This is a **sanctioned security exercise** for HackUTD 2026 on the user's **own rented GPU
box**. WS-B is the **blue-team dashboard** a law firm's security operator uses to review an
incident and approve the defender agent's proposed actions. It is **pure front-end plus a
record/CRUD API** — no attack code, no defender/agent logic, nothing offensive. A basic
version already exists (console renders a dashboard, scope, a NIST record and users today);
you are building it out to the full version.

## Goal

Build out the full Winstead incident-response dashboard:
- **NIST 800-61** record fields (full incident record, not the stub).
- **PDF export** of the record.
- **Roles** beyond a single admin (e.g. operator / approver / viewer).
- **Breach-notification deadline countdowns** (live timers against a deadline).
- **People-chat** (person-to-person messages on the incident).
- **Client-vs-operator framing** in the UI copy: the **law firm = client** running the AI
  jobs; **NMC = operator** monitoring to protect them. Label both sides. Add
  compromise-resilience framing (the dashboard runs off the box, so it survives a fully
  compromised cluster).

## The approval contract (it ALREADY EXISTS — build to it now, you are not blocked)

The defender's propose→approve flow is already in the codebase. You **render** the existing
`Approval` objects and call the existing approve/deny endpoints. There is no new contract to
wait for.

- The console already polls **`GET /snapshot`** → a `Snapshot` carrying
  `approvals: Approval[]`, `record`, `timeline`, `cluster`, `assets`, `attack`.
- **`Approval`** (models.py — camelCase, mirrored in `console/src/types.ts`):
  ```
  { id, requestedAt, requestedBy, action, target, rationale, policyReason, impact,
    status: "pending" | "approved" | "denied", decidedBy?, decidedAt? }
  ```
- Round-trip (already implemented, role-gated to admin/responder):
  **`POST /approvals/{id}/approve`** and **`POST /approvals/{id}/deny`** → return the updated
  `Approval`. Render Approve / Deny buttons that call these and reflect the returned status.

**WS-A will ADD four optional fields to `Approval`** — additive, so you are NOT blocked:
`rank` (number; lower = higher priority), `runbookRef` (string, e.g. `"RB-01#3"`), `risk`
(`"low"|"medium"|"high"`), `reversible` (bool). When present, **sort by `rank`** to show the
"ranked remediation plan" and display the runbook ref + risk on each item. When absent (before
A lands), render the flat list exactly as the console does today. That optional-field upgrade
is your only coupling to A, and it needs no code from me to start.

## What already exists (extend, don't replace — read these first)

- `console/` is a Vite + React app; `console/src/types.ts` is the wire contract mirror. Read
  both first and match the patterns.
- **Incident record** (`IncidentRecord` in models.py) already has: `title`, `status`,
  `phase`, `detectedAt`, `reportedBy`, `categories[]`, `severity`, `vector`,
  `affectedSystems[]`, `actionsTaken[]`, `nextSteps[]`, and **`notificationDueAt`** — use
  that last one for the **breach-deadline countdown**. Add any missing NIST 800-61 fields.
- **Roles already exist**: `admin | responder | viewer` (models.py `Role`), with
  `GET/POST /users` and role-gating via `require_roles(...)`. Enforce them in the UI; extend
  if you need finer roles.
- **Chat**: `POST /messages` already exists (send). You likely need a GET to list history —
  add it in your routes module.
- Endpoints live in `backend/app/main.py`. **Extend** enum/value sets; don't replace them.

## You own

- `console/*` — all the dashboard UI. **Exception:** do **not** add or touch an `evals`
  page/route — WS-C owns a separate evals page and its single nav entry; leave room for it.
- A new `backend/app/routes_incident.py` for the new record/scope/roles/chat endpoints,
  plus **one** additive include line in `backend/app/main.py` (put it with the other
  `include_router`/route registrations; don't rewrite existing routes).

## Don't touch

`defender.py`, `attacks.py`, `attacker/`, `hub.py`, `evals/`, WS-A's `routes_defender.py`.
Don't invent a second approvals system — consume WS-A's plan contract above.

## Done when

- Incident record exports to PDF with the NIST 800-61 fields.
- Roles exist and are enforced in the UI (approver can approve; viewer can't).
- A breach-notification deadline shows a live countdown.
- People-chat works on an incident.
- Both the client (law firm) and operator (NMC) sides are clearly labeled.
- The plan/approvals panel renders the contract above and round-trips approve/deny.
- Your ledger (`docs/ledger/ws-b.md`) logs every decision and file change, newest on top.

## Ledger (required)

Append to `docs/ledger/ws-b.md` as you go: status, decisions, changelog. The integrator
reads it to merge. An unlogged change is a merge surprise.

## PDF export — lazy path

Don't add a heavy PDF lib if the browser does it. `window.print()` against a print
stylesheet, or a single small client-side lib already common in the ecosystem, before
anything server-side. Pick the shortest path that produces a clean one-page record.
