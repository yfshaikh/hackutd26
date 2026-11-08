# WS-A ledger — Defender pattern

Append-only, newest on top. The integrator reads this to merge your work.
Keep it current as you go — it is cheaper than re-explaining later.

## Status
- State: core built AND the SA split verified on the live cluster (2026-11-07). RBAC
  applied; `auth can-i` matrix passes (read-only reads yes / writes no; executor = exactly
  the 5 containment verbs, no over-reach); end-to-end code path proven — minted read-only
  token lists pods but gets 403 on delete (the backend self-check). Not committed.
- Remaining to see live in the UI: run an incident so metrics populate + the 403 self-check
  lands in the timeline/decisions.jsonl. (Integration, not new code.)
- Action needed from a human: `kubectl apply -f deploy/30-agent-rbac.yaml` (mutates the
  cluster — classifier blocked me from applying). Until applied, the backend logs an admin
  fallback and the identity self-check reports "NOT read-only".
- Contract honored: the plan contract is additive fields on the existing `Approval` model
  (NOT a new type/endpoint). Fields: `rank`, `runbookRef`, `risk`, `reversible` — optional.
  WS-B consumes these; do not rename them without updating the WS-B spec + types.ts.
- Blocked on: —

## Decisions
<!-- (YYYY-MM-DD) what you decided — why — any alternative rejected -->
- (2026-11-07) "Ranked remediation plan" = 4 optional fields on the existing `Approval`
  flow, not a parallel `RankedRemediationPlan` type or a `/defender/plan` endpoint. Why:
  the propose→approve flow + approve/deny endpoints + console rendering already exist;
  extending is lazier and keeps the console working. Rejected: inventing a parallel plan
  object (would duplicate the approval system and break existing rendering).
- (2026-11-07) Runbook is a static table keyed by tool (`_RUNBOOK` in defender.py).
  Rank order = quarantine(1) → delete pod(2) → delete cronjob(3) → revoke SA(4) →
  cordon(5): stop the bleeding, then persistence, then identity. Adjustable — flagged as a
  default. A config-driven runbook is the §12 Future item.

- (2026-11-07) Security-review fix: executor RBAC was a cluster-wide ClusterRole (over-
  privileged — the exact anti-pattern WS-A demonstrates against). Scoped it to a namespaced
  `Role`+`RoleBinding` in lawfirm; only `nodes` (cluster-scoped, unavoidable) stays a tiny
  ClusterRole. Pinned `rolebindings` delete to `resourceNames: [notebook-dev]`. Added a
  server-side `_require_lawfirm()` guard to the namespaced executors (defense-in-depth).
  Read-only stays cluster-wide READ by design (investigate broadly, act narrowly) — noted
  in the manifest.

## Changelog
<!-- (YYYY-MM-DD) what changed — files touched — done/wip -->
- (2026-11-07) Metrics: `defender.metrics()` computes current-incident outcomes from
  decisions.jsonl (time-to-contain, autonomous vs approved counts, mean time-to-approve,
  GPU-hours of mining prevented), scoped to decisions since `detectedAt` so stale runs don't
  inflate it. Exposed at `GET /defender/metrics` via new `routes_defender.py` + one additive
  include in main.py (same `current_user` auth as /snapshot). Unit self-check passed;
  TestClient confirms the route is live (401 unauth). NOTE verified in passing: `include_router`
  works fine here despite `.path` inspecting as '' — a quirk of this pinned FastAPI (0.162.2);
  WS-B's `routes_incident` include is also fine (GET /incident/record → 401, registered).
  **done.**
- (2026-11-07) Added `rank`/`runbookRef`/`risk`/`reversible` (optional) to `Approval`
  (models.py); added `_RUNBOOK` table + `_runbook_for()` and populated the fields when an
  approval is created (defender.py `_dispatch`). Syntax-checked. **done (this slice).**
- (2026-11-07) Read-only/executor split landed in code: `deploy/30-agent-rbac.yaml`
  (agent-readonly ClusterRole = get/list/watch only; agent-executor = exactly the 5
  containment verbs). `k8s.py`: `agent_readonly*()` / `executor*()` clients, tokens minted
  in-memory via TokenRequest (never read from a file, never printed), admin fallback logged
  once if SAs absent. `defender.py`: read tools → read-only client, mutating tools →
  executor client; backend detection/telemetry stays on admin (SIEM boundary);
  `verify_readonly_identity()` attempts a delete with the read-only client at loop startup
  and logs the 403 as proof. Syntax-checked; manifest structure verified. **wip — needs
  cluster apply to activate (see Status).**
- Next: metrics endpoint from decisions.jsonl (time-to-detect, time-to-contain,
  GPU-hours saved).
