# WS-B ledger — Winstead full

Append-only, newest on top. The integrator reads this to merge your work.
Keep it current as you go — it is cheaper than re-explaining later.

## Status
- State: **done** (full dashboard: NIST record + PDF, roles, deadlines, chat, framing,
  ranked-plan rendering)
- Contract honored: consumes WS-A's **additive** `Approval` fields (`rank`, `runbookRef`,
  `risk`, `reversible`) — no new plan type, no second approvals system. Approve/deny still
  round-trips through the existing `POST /approvals/{id}/approve|deny`. The `IncidentRecord`
  enum/value sets were extended, not replaced.
- Blocked on: — (WS-A's fields are already in the working tree and render; a flat list still
  renders if they are absent)

## Decisions
- (2026-11-07) **PDF export = `window.print()` + a print stylesheet**, per the spec's lazy
  path. No PDF library, no server-side renderer. `@media print` hides the shell/nav/band/
  scope/cluster/timeline/chat, expands the record panel, hides buttons, and adds a print-only
  header (`NMC operator console · client: Halloran & Vance LLP · exported <time>`). Browser
  "Save as PDF" produces the deliverable.
- (2026-11-07) **Full NIST 800-61 record is additive.** Added optional `summary`, `impact`,
  `rootCause`, `evidence[]`, `containmentMeasures[]`, `lessonsLearned`, `incidentCommander`,
  `notifiedParties[]`, `notificationDeadlines[]`, `closedAt`. Existing fields and the
  defender's `_record_merge` keep working; a record created by the defender gets the new
  fields as empty defaults.
- (2026-11-07) **Multiple breach clocks, one legacy fallback.** `notificationDeadlines` is a
  list of `{label, dueAt, jurisdiction?, status}`; the UI ticks every second. If the list is
  empty, it falls back to the existing `notificationDueAt`, so the defender's current
  exfiltration path still shows a live countdown with no changes to defender.py.
- (2026-11-07) **Roles = admin / approver / operator / responder / viewer.**
  - `approver`: approve/deny only (separation of duties).
  - `operator`: chat + record/scope edits, cannot approve.
  - `responder`: legacy superset (approve + chat + edits).
  - `viewer`: read only.
  This required three small shared-file edits, logged below: `models.py` `Role` literal,
  `auth.py` `set_role()`, and the role tuples on the existing approve/deny/messages routes
  in `main.py` (adding `approver` / `operator`). No route was rewritten.
- (2026-11-07) **People-chat uses the human timeline**, per the spec's "POST /messages
  already exists". Added `GET /messages` in `routes_incident.py`; the Chat panel hydrates from
  it once, then merges the live SSE timeline by id (no polling, no duplicate messages).
  Record/scope updates also appear there because they are human audit events.
- (2026-11-07) **Two-sided framing is a persistent strip, not a modal.** Client = Halloran &
  Vance LLP (runs the AI jobs), Operator = NMC SOC (monitors and protects), plus a
  compromise-resilience card. Also reflected in the top bar and sign-in copy.
- (2026-11-07) **Record editing is role-gated** (`admin`/`responder`/`operator`) and uses a
  single `PATCH /incident/record` with only present fields; every save appends a
  `RecordAction` and a human timeline entry, so the audit trail is automatic.
- (2026-11-07) **No evals page/route touched** — WS-C owns it; the nav has room for one.

## Changelog
- (2026-11-07) **done** — `console/README.md` + `README.md`: documented the full dashboard
  features, the five-step attack chain, and the new deploy manifest apply order.
- (2026-11-07) **done** — `backend/app/routes_incident.py`: added a non-null guard for
  required record fields and ISO validation for deadlines (400s instead of letting a null
  reach the model). Verified: null title/deadlines -> 400, clear summary -> 200, bad
  deadline -> 400, good deadline -> 200.
- (2026-11-07) **done** — `backend/app/routes_incident.py` (new): `GET/PATCH
  /incident/record`, `GET /incident/scope`, `PATCH /incident/scope/{asset_id}`,
  `GET /messages`, `GET /roles`, `PATCH /users/{user_id}/role`. ISO timestamp validation,
  role gating, audit entries.
- (2026-11-07) **done** — `backend/app/models.py`: `Role` extended; `NotificationDeadline`,
  `IncidentRecordPatch`, `RoleInfo`, `SetRoleBody`, `ScopePatch`; `IncidentRecord` extended
  with the full NIST fields (all additive/optional). (Also contains WS-D's `AttackStepId`
  `"ddos"` addition — disjoint line.)
- (2026-11-07) **done** — `backend/app/main.py`: one additive `app.include_router(
  incident_router)`; approval role tuples now include `approver`; `POST /messages` now
  includes `operator`. Existing routes otherwise untouched.
- (2026-11-07) **done** — `backend/app/auth.py`: additive `AuthStore.set_role()` for the
  admin role-change endpoint.
- (2026-11-07) **done** — `console/src/types.ts`: mirrored the WS-A `Approval` fields, new
  record fields, `NotificationDeadline`, `IncidentRecordPatch`, `RoleInfo`, extended `Role`;
  added `"ddos"` to `AttackStepId` for WS-D.
- (2026-11-07) **done** — `console/src/api.ts`: `getRecord`, `patchRecord`, `getScope`,
  `patchScope`, `getMessages`, `listRoles`, `setUserRole`, plus a PATCH helper.
- (2026-11-07) **done** — `console/src/components/DecisionBand.tsx`: pending approvals sort
  by `rank`, "Ranked remediation plan" heading, rank badge, runbook ref / risk / reversible /
  target tags, role-aware read-only copy.
- (2026-11-07) **done** — `console/src/components/IncidentRecord.tsx`: full NIST record
  rendering, live breach clocks, "Edit record" + "Export PDF" buttons, print header and
  resilience footer.
- (2026-11-07) **done** — `console/src/components/RecordEditor.tsx` (new): full record
  editor incl. NIST fields and a `Label | ISO | jurisdiction | status` deadline editor.
- (2026-11-07) **done** — `console/src/components/BreachCountdown.tsx` (new): live
  second-by-second countdowns with overdue/due/soon tones and legacy fallback.
- (2026-11-07) **done** — `console/src/components/Chat.tsx` (new): people-chat panel with
  GET history + live SSE merge + role-gated composer.
- (2026-11-07) **done** — `console/src/components/Framing.tsx` (new): client/operator/
  compromise-resilience strip; wired into `pages/CommandCenter.tsx` with Chat in the right
  column (`.area-right`).
- (2026-11-07) **done** — `console/src/pages/Users.tsx`: five-role catalogue, role selector
  on add, per-user role change (admin, self-change disabled).
- (2026-11-07) **done** — `console/src/components/Timeline.tsx`: composer uses `canChat`
  (approvers can decide but not post); `labels.ts`: `ROLE`/`ROLE_ORDER`, `canAct`,
  `canChat`, `canEditRecord`, `RISK`; `format.ts`: `remaining`, `toLocalInput`,
  `fromLocalInput`; `TopBar.tsx` + `Login.tsx` + `App.tsx`: two-sided copy.
- (2026-11-07) **done** — `console/src/styles.css`: framing, ranked plan, deadlines, record
  editor, chat, roles, and the full `@media print` stylesheet.
- (2026-11-07) **done** — `console/API.md`: documented the new endpoints, five roles, record
  fields and the WS-A plan fields.
- (2026-11-07) **verified** — `cd console && npm run build` (tsc + vite) passes. Backend
  TestClient checks: admin can patch the record + read chat; viewer gets 403 on record patch,
  approve and chat; approver gets 404 (role passed) on a missing approval but 403 on chat and
  record patch; `/roles` returns all five roles.
