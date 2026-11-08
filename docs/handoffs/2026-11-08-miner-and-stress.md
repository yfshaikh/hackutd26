# Handoff — vanishing miner investigation + full stress test

**Date:** 2026-11-08
**Scope:** Part A (miner disappears before containment) and Part B (all attack paths), plus the two follow-up auth fixes.
**Status:** miner race fixed; 6 of 8 scenarios pass (two with caveats); 2 scenarios have agent-reasoning/containment gaps that are reported but **not** fixed.

---

## TL;DR

1. **The miner was never self-terminating.** It is a bare Pod running `while True` with `restartPolicy: Never`.
2. The “vanished” pod and the `quarantine_pod → Not Found` were caused by **multiple backend processes** racing on the same cluster. One backend deleted the pod; another backend's stale Advisor tried to quarantine it.
3. Fixed with a **singleton flock** (a second backend now refuses to start) plus a **deletionTimestamp filter** in detection (GPU pods stay Terminating for ~50 s, causing false “still rogue” residuals).
4. Also fixed: `/reset` now deletes every attacker object independently (one 404 no longer strands the rest), token refresh (re-mint before expiry), and fail-closed ServiceAccount identities (no admin fallback).
5. Stress results: scenarios 1, 2, 3, 6, 7, 8 pass (some with caveats); **4 (egress flood)** and **5 (everything)** fail on agent reasoning/containment.

---

## Part A — root cause and fix

### What the miner actually does

`backend/app/attacks/bodies.py`:

- `_MINER_PY` is `while True`, with `[matmul]` output every 200 iterations (`:29-37`).
- `_miner_pod_body` creates a bare `kind: Pod`, `restartPolicy: Never` (`:55-70`, specifically `:63`).
- No `activeDeadlineSeconds`, no Job, no TTL.

### Evidence it was deleted, not self-terminated

- Kubernetes events show `Killing` at exactly the defender's `delete_pod` timestamps:
  - `kube-sync-a2d81a`: started 14:09:43, `Killing` 14:11:23; `delete_pod` logged 14:11:23.
  - `kube-sync-b3f76d`: started 14:17:49, `Killing` 14:19:09; `delete_pod` logged 14:19:09.
- In the bad run, the failing line was a **second** quarantine 7 s *after* a successful delete:
  - `14:19:09.05 delete_pod kube-sync-b3f76d` → `deleted pod/...`
  - `14:19:16.19 quarantine_pod kube-sync-b3f76d` → `error labeling pod: Not Found`
- The defence's own `decisions.jsonl` contained the delete; it came from the *other* backend process, which is why it looked like “nothing deleted before quarantine” if you read one pipeline's story.

### Why multiple backends existed

At one point `ps` showed three `uvicorn app.main:app --port 8000` app processes (plus `uv run` wrappers), started at different times. Each had:

- its own `pending_actions`, `_handled` set and detection loop;
- its own startup `verify_readonly_identity` row (14:15:45, 14:16:34, 14:17:45, 14:19:28);
- a shared `decisions.jsonl` and SQLite file.

One backend contained the miner; another's stale plan ran `quarantine_pod` and got `Not Found`. That is the whole “vanishing miner” story.

### Fixes

| File | Change |
|---|---|
| `backend/app/main.py` | `_acquire_singleton_lock()` acquired at startup (`fcntl.flock`, per checkout). A second backend exits with `Application startup failed. Exiting.` Verified. |
| `backend/app/defender.py` | `_detect()` now filters out pods and CronJobs with `metadata.deletionTimestamp` before evaluating rules. Prevents verify passes and the 4 s detector from re-escalating objects already being deleted. |

### Re-run result

Single backend, miner-only run: pod observed 14:26:12 → 14:28:58 (~166 s), then quarantined + deleted by the Advisor. No redundant `Not Found`; verify logged `Confirmed: all rogue workloads cleared.` Scenarios 1 and 3 also ended cleanly after the fixes.

**No change to the miner/attack code was needed.**

---

## Part B — stress results (single backend, clean cluster)

All runs driven over HTTP (`/reset`, `/attack/{step}`, `/snapshot`, `/incident/record`, `/approvals/...`), never via internal functions. Each run reset between scenarios.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | Cryptojacking | **PASS** | 62.3 s to contain; one quarantine + delete; one revoke card (`ap-88f284b6`); `cryptojacking` hypothesis filed; verify confirmed. Caveat: also read unrelated `persistence` runbook. |
| 2 | Exfiltration | **PASS with caveat** | `model-weights=exfiltrated`; severity `critical`; 72 h clock `2026-11-11T14:37Z`; drop-site log 302,335,262 bytes (288.3 MiB). Caveat: the agent never called `update_scope`; deterministic `_check_exfil_evidence` set scope/clock one tick after the verify marker. Impact text omitted the byte count. |
| 3 | Persistence | **PASS** | `delete_cronjob log-rotate` 14:45:26 **before** pod `log-rotate-...` quarantine/delete at 14:45:27/28; verify confirmed; runbooks `persistence` + `containment-actions`. |
| 4 | Egress flood | **FAIL** | Flood pod quarantined + deleted (66.1 s), but categories were `cryptojacking`, hypothesis only `cryptojacking: ruled_out`, runbooks read `containment-actions`, `cryptojacking`, `persistence` — **`egress-flood` was never read**. |
| 5 | Everything | **FAIL** | One revoke card (`ap-1af2a338`), no crash, but after both passes `data-sync-f7023a` and `net-probe-dde94b` were **quarantined, not deleted**; verify logged `2/2: rogue state still present`; record omitted persistence/DoS and wrongly said no exfiltration. |
| 6 | Idempotency | **PASS with caveat** | Second miner run reused the same pending revoke (`ap-4c050f38`); hypotheses updated in place (no duplicate names); `nextSteps` stayed at 4; two `Confirmed` markers. `duplicate-suppressed` log count was 0 because the second Advisor never re-proposed it. |
| 7 | Human gate | **PASS** | Approve → Executor row `Executed approved action: revoke_service_account() — deleted RoleBinding notebook-dev`; deny → `Human denied: revoke_service_account().`; no pending card after either. |
| 8 | Reset + history | **PASS** | Reset archived the incident; `/incidents` lists it; detail returns the same record and a 24-entry timeline; read-only GET works. |

### Cross-cutting findings

- **Runbooks: FAIL.** The “only confirmed scenario(s)” rule is not reliable:
  - s1 read `persistence` (irrelevant),
  - s2 never read `data-exfiltration`,
  - s4 never read `egress-flood`,
  - s5 never read `data-exfiltration`.
- **Hypotheses: PARTIAL/FAIL.** At least one hypothesis was filed per run, but s2/s4 filed only `cryptojacking: ruled_out` and missed the actual scenario. Other candidates are rarely ruled out.
- **Record:** all four fields (`summary`, `impact`, `rootCause`, `vector`) were filled in every run, but s5 is misleading and s2’s scope/clock came from the deterministic detector, not the agent.
- **Convergence:** only s5 failed to converge; no agent printed “reached its step limit.”
- **Backend errors:** none (no uvicorn tracebacks).
- **Paging:** every approval showed `not called: paging off`.

---

## Auth fixes (follow-up request)

| File | Change |
|---|---|
| `backend/app/k8s.py` | Cached agent clients now keep `(client, refresh_at)` and re-mint 5 minutes before the API server’s `expirationTimestamp` (server-granted TTL honored, not a hard-coded hour). `reset_agent_clients()` still forces it. |
| `backend/app/k8s.py` | Mint failure now raises `AgentIdentityUnavailable`; **no fallback to the admin client**. |
| `backend/app/defender.py` | Read tools catch `AgentIdentityUnavailable` and return an error string; `run_tool_approved` refuses rather than retrying as admin; `verify_readonly_identity` logs `NOT verified`; `run_agent` preflights both scoped identities and pauses the pipeline if unavailable. |

Unit-tested with mocks: cache reuse, refresh on the server-granted expiry, and fail-closed on 403. No real token values were printed or logged.

---

## Reset cleanup fix

`backend/app/attacks/steps.py` — `_delete_attack_objects()` now wraps each delete in its own `try/except`. Previously one `ApiException` (often a 404 on a pod already gone) aborted the whole loop and left other attacker objects behind. Verified with two labelled dummy pods (one deleted first): `/reset` removed the survivor and returned `removed 3 attacker object(s)`.

---

## What was not fixed (recommended next work)

1. **Advisor runbook selection** — prompt/tool-choice issue; s2/s4/s5 miss the relevant runbook. Consider selecting the runbook in code from confirmed hypotheses/categories, or make the prompt require naming the confirmed scenario before any containment call.
2. **Scenario 5 containment** — the verify pass must delete every quarantined unknown pod before summarizing. Options: add a deterministic “delete all unknown/quarantined pods” step after the second pass, or give the verify Advisor more rounds and an explicit delete checklist. Do not just increase the prompt text and assume it works; re-run s5.
3. **Investigator hypothesis coverage** — require a verdict for each candidate (`cryptojacking`, `data-exfiltration`, `persistence`, `egress-flood`) before handoff.
4. **Exfiltration scope timing** — have the agent call `update_scope` for `model-weights` (and include the byte count in `impact`) instead of relying on the 4 s detector tick after the run.
5. **No revoke card in s2/s4** — the relevant runbooks say to request `revoke_service_account`; the Advisor only listed it in next steps. Decide whether the table requires it.
6. **`duplicate-suppressed` marker** — s6 achieved one card without ever hitting the dedupe path (the second Advisor saw `_pending_summary` and did not re-propose). If the log marker is part of acceptance, add a test that forces a second proposal.

---

## How to run / verify

```bash
# exactly one backend — the lock will reject a second one
cd backend && uv run uvicorn app.main:app --port 8000

# health
curl -s http://localhost:8000/healthz

# clean slate
curl -X POST http://localhost:8000/reset

# a scenario
curl -X POST http://localhost:8000/attack/gain-access
curl -X POST http://localhost:8000/attack/start-miner
```

- Console: Vite on `:5173`; attacker UI on `:5180`.
- The scenario harness used for this report lives at
  `/private/var/folders/pg/28qm3hws55x17kb9vxht8jk00000gn/T/opencode/stress.py`
  (temporary, not committed). It logs in with the runtime `ADMIN_EMAIL`/`ADMIN_PASSWORD`, waits for the deterministic “Confirmed” marker, and dumps decisions/timeline/metrics as JSON.
- Evidence: `backend/logs/decisions.jsonl`; history in `backend/data/incidents.db`; live UI at Command Center / Incident / Runbooks.

---

## Repo state

No commits were made. Files changed by this session:

```
 M backend/app/attacks/steps.py   # per-object reset cleanup
 M backend/app/defender.py        # fail-closed identities, deletionTimestamp filter
 M backend/app/k8s.py             # token refresh, fail-closed SA clients
 M backend/app/main.py            # singleton backend lock
```

The working tree also contains pre-existing uncommitted work from earlier sessions (floor/cluster drawer, runbooks page, agent sidebar, specs). Do not revert those. Full `git status --short` at handoff:

```
 M backend/app/attacks/steps.py
 M backend/app/cluster.py
 M backend/app/defender.py
 M backend/app/hub.py
 M backend/app/k8s.py
 M backend/app/main.py
 M backend/app/models.py
 M backend/app/routes_defender.py
 M console/API.md
 M console/src/App.tsx
 M console/src/api.ts
 M console/src/components/AgentMap.tsx
 M console/src/components/BreachCountdown.tsx
 M console/src/components/ClusterView.tsx
 M console/src/components/IncidentRecord.tsx
 M console/src/components/NodeDetail.tsx
 M console/src/components/Status.tsx
 M console/src/components/Timeline.tsx
 M console/src/components/TopBar.tsx
 M console/src/floor/Floor3D.tsx
 M console/src/pages/FloorPage.tsx
 M console/src/pages/IncidentPage.tsx
 M console/src/styles.css
 M console/src/types.ts
?? backend/app/routes_cluster.py
?? backend/runbooks/
?? console/src/components/PodDetail.tsx
?? console/src/pages/Runbooks.tsx
?? docs/handoffs/
?? docs/specs/07-deepseek-miner-and-stress.md
```
