# Handoff to DeepSeek — investigate the vanishing miner pod, then stress-test every scenario

You are picking up a working HackUTD 2026 demo: a live attacker-vs-defender GPU incident-response
system on a real k3s cluster (rented Brev box). Repo: `/Users/yusufshaikh/Desktop/Projects/hackutd26`.
Your job has two parts: **(A)** find out why the miner pod disappears before the Advisor contains it, and
fix it if it is a demo bug; **(B)** stress-test every attack path end to end and report what breaks.

## Hard rules (read before doing anything)

> Never read, cat, grep, tail, source, or otherwise open `.env` or any
> secrets file, by any means, including via a script or subprocess. This
> also bans unscoped `grep -rn` from a repo root — always scope a grep to a
> directory. If you need a credential, read it from `os.environ` /
> `process.env` at runtime and never print it. If something appears to be
> missing, stop and report it; do not go looking for the value.

- **Do not commit.** Do not run `git commit`, `--amend`, `merge`, `cherry-pick`. Leave changes in the working
  tree and list them in your report; the user reviews and commits.
- The working tree already has uncommitted changes from other work (floor/cluster files, the agent sidebar,
  runbooks). Don't revert anything you didn't write.
- Don't call internal functions like `defender._dispatch(...)` from a test script against the real backend
  package — it appends to the real audit log `backend/logs/decisions.jsonl`. Drive everything through HTTP
  or the UI. If you must, note which log lines you created and remove exactly those.

## How the system runs

- Backend: FastAPI on **:8000** — `cd backend && uv run uvicorn app.main:app --port 8000` (no `--reload`;
  restart it after backend edits). Console (defender UI): Vite on **:5173**. Attacker UI: Vite on **:5180**.
- Local dev login for the console: the defaults in `backend/app/config.py` (admin account). Restarting the
  backend logs the console out (sessions are in memory).
- Attack steps (unauthenticated, for testing): `POST /attack/{step}` with step in `gain-access`, `start-miner`,
  `steal-weights`, `persistence`, `ddos` (check `backend/app/attacks/steps.py` for the exact ids).
  Always `gain-access` first. `POST /reset` cleans the cluster and archives the incident to SQLite.
- Pipeline (`backend/app/defender.py`): deterministic detection rules (`_detect`, every ~4 s) wake three
  Nemotron agents in sequence — **Triage → Investigator → Advisor** — then a verify-and-reconverge pass.
  The **Executor** is not an agent, just the write identity. A full run takes ~2–3 minutes.
- Evidence to read after a run:
  - `backend/logs/decisions.jsonl` — every tool call, approval, duplicate-suppressed request (one JSON per line).
  - Console → Command center: live timeline; click an agent mascot for its sidebar (**Trace** / **Setup** tabs).
  - Console → **Incident** page (`/record`): summary, impact, root cause, hypotheses, actions, open items.
  - Console → **Runbooks** page; the agents read the same files through the `get_runbook` tool.
- Kubernetes: `kubectl` against the k3s cluster, namespace `lawfirm` (attacker objects carry
  `hackutd/attack=true`, legit ones `owner=law-firm|platform`).

## Part A — the vanishing miner

**Symptom (seen twice in a row):** `start-miner` creates `kube-sync-xxxxxx`; the Detector fires
("Unknown pod … with no owner label"); Triage and the Investigator read it fine (`describe_pod`, `get_pod_logs`
show `[matmul] 200 iters …`). But ~1.5–2 min later the Advisor's `quarantine_pod` returns
`error labeling pod: Not Found` — the pod is already gone, and the Advisor's summary says it "self-terminated".
Nothing in the defender deleted it (check `decisions.jsonl`: no `delete_pod` executed before the quarantine).

**Investigate, don't guess:**
1. Read the miner's pod spec and command: `backend/app/attacks/bodies.py` (+ `steps.py`, `runtime.py`).
   Does the matmul loop run a fixed number of iterations / a fixed duration and then exit? What is
   `restartPolicy`? Is it a bare Pod, a Job (with `activeDeadlineSeconds` / `ttlSecondsAfterFinished`)?
2. Reproduce with timing: `POST /reset`, `gain-access`, `start-miner`, then
   `kubectl get pods -n lawfirm -w` (and `kubectl get events -n lawfirm --sort-by=.lastTimestamp`) until it
   disappears. Note the exact lifetime and the reason (Completed? Evicted? OOMKilled? deleted?).
3. Check whether anything else removes it: the reset logic, a k3s GC, the GPU fault simulator
   (`simulatedFault` appears in `gpu_status`), or the attacker runtime.

**Fix (only if it's a demo bug):** the miner should keep running until the defender contains it, with a long
safety cap (e.g. 15–20 min) so a forgotten demo doesn't burn the GPU forever. Keep the change minimal and
inside the attack code; do not change detection or agent behaviour to compensate. Re-run once and confirm the
Advisor's `quarantine_pod` → `delete_pod` now succeed (Executor rows in the timeline, `executed` in
`decisions.jsonl`, and `Confirmed: all rogue workloads cleared.` from the verify pass).

## Part B — stress test every path

Between scenarios, `POST /reset` and wait until the console shows no open incident. For each run, record:
time to contain, which agents ran, tool calls per agent, approvals requested, final record fields.

| # | Scenario | Steps | What must be true |
|---|----------|-------|-------------------|
| 1 | Cryptojacking | gain-access → start-miner | Miner quarantined + deleted autonomously; one `revoke_service_account` approval; Investigator files a `cryptojacking` hypothesis (`record_hypothesis`) |
| 2 | Exfiltration | gain-access → steal-weights | `model-weights` scope = exfiltrated; severity critical; **72 h client-notification clock** appears on the Incident page; impact says what left |
| 3 | Persistence | gain-access → persistence | CronJob deleted **before** its pods (runbook order); verify pass reports nothing respawned (or re-converges once, then clears) |
| 4 | Egress flood | gain-access → ddos | Flood pod quarantined fast; category reflects DoS; no GPU-based false reasoning |
| 5 | Everything | gain-access → miner → steal-weights → persistence → ddos (a few seconds apart) | Exactly **one** revoke card total; no crash; final record coherent |
| 6 | Idempotency | run #1 twice without reset (start-miner again after containment) | Still one revoke card (`duplicate-suppressed` in `decisions.jsonl`); hypotheses update in place (no duplicate names on the Incident page); Open items is replaced, not appended (≤ ~4 items) |
| 7 | Human gate | after any run, Approve the revoke in the console; on another run, Deny it | Approve → Executor row "Executed approved action"; Deny → "Human denied" on the record; neither re-proposed afterwards |
| 8 | Reset + history | `POST /reset` after a run | Incident appears in the Incident page's switcher; opening it is read-only and shows the same fields |

For **every** run also check:
- **Runbooks:** the Advisor calls `get_runbook` for the confirmed scenario(s) in its first round
  (grep `"get_runbook"` in `decisions.jsonl`) and names them in its summary. If it never calls it, report the
  exact Advisor trace — do not paper over it. **Known issue to verify:** before the last prompt tweak the
  Advisor read *all five* scenario runbooks on a miner-only incident; the prompt now says "ONLY the confirmed
  scenario(s), never all". Confirm it reads just the relevant one(s) (e.g. cryptojacking [+ identity-compromise]).
- **Hypotheses:** at least one `record_hypothesis` from the Investigator; note whether it also rules the other
  candidates out (it currently tends not to — report, don't fake it).
- **Record:** `summary`, `impact`, `rootCause`, `vector` are filled on the Incident page by the end.
- **Convergence:** no agent says "reached its step limit"; every agent ends with a handoff or summary.
- **No backend errors:** scan the uvicorn output for tracebacks.
- **Paging:** approval card shows `not called: paging off` (Cartesia is off by default — don't enable it).

## Invariants you must not break

1. Force-answer last round + `temperature=0` in `_run_role`.
2. `_approval_sig` de-dup — one card per identical pending action.
3. Per-agent tool scope enforced in code (`allowed` in `_run_role`); only the Advisor gets mutating tools.
4. Ports/CORS: 8000 / 5173 / 5180.
5. Timeline entry fields the UI depends on: `tool`, `toolResult`, `reasoning`, `agent`, `traceOnly`, `hypothesis`.
6. Nothing slow or failable on the detection loop thread.

## Report back (keep it short)

1. **Part A:** root cause of the vanishing miner (with the evidence — pod lifetime, reason, file:line), the
   fix (diff summary) and the re-run result.
2. **Part B:** the table above with PASS/FAIL per row and one line of evidence each.
3. Anything you changed (files + why), and anything you found but did not fix.
4. `git status --short` at the end. Do not commit.
