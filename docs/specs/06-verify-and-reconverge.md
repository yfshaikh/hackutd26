# Spec 06 — Verify-and-reconverge (the Advisor checks its own work)

**Lane:** E (backend; shares `defender.py` with Spec 05 — do 05 and 06 in the SAME chat)
**Files:** `backend/app/defender.py` (`run_agent` / the Advisor stage; reuse `_detect`).
**Read first:** `backend/app/defender.py` — `run_agent`, `_run_role`, `_detect`, `detection_tick`, `ADVISOR_PROMPT`,
the approval idempotency (`_approval_sig`, the needs-approval branch in `_dispatch`).

**Goal (the strongest "this isn't a chatbot" signal):** after the Advisor acts, it **re-observes** to confirm
containment actually held, and **re-acts** if it didn't — a pod respawned, a cronjob is still there, the GPU is
still pinned, a second foothold exists. Observe → act → **verify** → re-act, bounded.

## Approach (code-level reconverge — robust, reuses `_detect`)
In `run_agent`, after the Advisor's containment stage:
1. Log **"Verifying containment…"** to the timeline.
2. Re-run `_detect()` (read-only) to see what rogue state remains on the live cluster.
3. If rogue findings remain (e.g. the `log-rotate` CronJob respawned a miner pod after the first delete), feed
   those residual findings back to the Advisor as a short follow-up context and run the Advisor **once more** to
   clear them. Bound this to **at most 2 verify passes**, then stop.
4. When `_detect()` comes back clean, log **"Confirmed: all rogue workloads cleared."** (or, if it had to act again,
   **"Re-contained: a cronjob respawned a miner; removed again."**) and finalize.

This directly catches the persistence case: deleting the miner pod isn't enough while the CronJob keeps recreating
it — verify-and-reconverge removes the cronjob AND clears the pod it already spawned.

## Must-preserve invariants (do NOT regress)
- **Bounded:** at most 2 verify passes — never an infinite loop. The background `detection_loop` already re-checks
  every 4s, so the in-run verify is a bounded supplement, not a competitor.
- **Idempotent:** re-running the Advisor must not double-file approvals — the `_approval_sig` de-dup already
  guarantees one `revoke_service_account` card; keep it intact (a verify pass must not create a second revoke).
- Keep `temperature=0` and the **force-answer final round** so each Advisor pass still terminates cleanly.
- Mutating actions still go through `classify()` / `_dispatch` (policy gate unchanged) — verify re-acts through the
  same gate, it doesn't bypass approvals.

## Acceptance
- **Persistence scenario:** the Advisor deletes the `log-rotate` CronJob, then a verify pass catches/clears any
  pod it respawned before finalizing; the timeline shows an explicit **verify** step and a confirmed-clear line.
- **Simple scenarios (miner/exfil/ddos):** verify runs once, finds it clean, finalizes — no extra actions.
- Still exactly **one** `revoke_service_account` approval across the run (de-dup holds).
- No step-limit regressions; bounded to ≤2 passes; the end-to-end attack run (Claude will run it) passes for all four attacks.
