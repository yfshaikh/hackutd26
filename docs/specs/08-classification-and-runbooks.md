# Spec 08 — Accurate attack classification + the right runbook (prompt-level)

**Lane:** backend agents. **Files:** `backend/app/defender.py` (prompts + one context line), `backend/runbooks/*.md`
(signal sections only). Touch nothing else.

## Hard rules

> Never read, cat, grep, tail, source, or otherwise open `.env` or any
> secrets file, by any means, including via a script or subprocess. This
> also bans unscoped `grep -rn` from a repo root — always scope a grep to a
> directory. If you need a credential, read it from `os.environ` /
> `process.env` at runtime and never print it. If something appears to be
> missing, stop and report it; do not go looking for the value.

- Do not commit. Leave changes in the working tree and report `git status --short` + `git diff --stat`.
- Exactly ONE backend may run (`cd backend && uv run uvicorn app.main:app --port 8000`). A singleton lock now refuses a
  second one; if it refuses, find and stop the old process — don't work around the lock.
- Don't call `defender._dispatch` / `_do_*` from scripts: they write to the real audit log `backend/logs/decisions.jsonl`.
- Keep the invariants: force-answer last round + `temperature=0`; `_approval_sig` de-dup; per-agent tool scope in
  `_run_role`; timeline fields `tool/toolResult/reasoning/agent/traceOnly/hypothesis`.

## Why it misclassifies today (evidence from `decisions.jsonl`, egress-flood run at 14:46)

1. **Triage labels before it looks.** It set `categories: ["unauthorized-access","cryptojacking"]` before any read. Its
   prompt's example categories have no DoS/flood option.
2. **The Investigator had no name for what it saw.** It read `EGRESS-FLOOD target=sink.drop-site.svc:80 connections=25…`
   but its candidate list is cryptojacking / exfiltration / persistence / lateral movement — no egress flood — so all it
   could file was `cryptojacking: ruled_out`.
3. **Mining bias everywhere.** The Investigator is told to always call `mining_impact`; the Advisor must state "the $
   compute impact". Every incident gets narrated as mining.
4. **Runbook choice follows the handoff wording.** The handoff never said "egress flood", so the Advisor picked
   cryptojacking/persistence. It also contains *before* reading the runbook.

The agents keep making the hypothesis — we fix their vocabulary and their evidence rules, not replace them with code.

## Changes

### 1. One shared attack-signature table in `_SCENARIO` (all three agents see it)

Add a compact table after the scenario text. Exact scenario ids must match the runbook file names and the hypothesis
names, so the Advisor can map hypothesis → runbook mechanically:

| id | Strong signals (any one is enough to call it *likely*) | NOT this if |
|----|------|------|
| `cryptojacking` | unowned pod **requesting `nvidia.com/gpu`**; GPU pinned ~100%; logs with `[matmul]`, `xmrig`, `stratum` | pod has no GPU request |
| `data-exfiltration` | non-model-server pod **mounting the `model-weights` PVC**; `curl`/`PUT`/upload in its command; drop-site evidence | nothing mounts the weights |
| `persistence` | a **CronJob not on the allowlist**; pods named `<cronjob>-<digits>-xxxxx`; a pod that **reappears after deletion** | no non-allowlisted CronJob |
| `egress-flood` | unowned pod with **no GPU and no PVC**; logs with `EGRESS-FLOOD`, connection counters, one external `target=host:port` | — |
| `identity-compromise` | **always present alongside the above**: attacker objects were created with the notebook's service account (root cause) | — |

Add the rule: *"An unowned pod is NOT evidence of any one scenario by itself — every attack creates one. Classify by
the discriminating signal (GPU request, weights mount, CronJob, flood logs). Read the pod (describe + logs) before you
name a category. A completed pod (phase Succeeded) still has readable logs — read them."*

### 2. Triage

- Do not set `categories` until it has run `describe_pod` + `get_pod_logs` on each unowned pod. Categories come from the
  table ids above (plus `unauthorized-access`).
- Remove the hard-coded example list that omits flood; point at the table.

### 3. Investigator

- Candidates = the four scenario ids from the table (`cryptojacking`, `data-exfiltration`, `persistence`,
  `egress-flood`); drop "lateral movement" (no attack produces it — it only adds noise).
- `record_hypothesis` names must be exactly those ids (so the console and the Advisor line up). Before handoff, **every**
  candidate gets a verdict; ruling out with the "NOT this if" evidence is expected and good.
- `mining_impact` ONLY if `cryptojacking` is confirmed/likely. `lookup_cve` stays for every incident (entry point is
  shared).
- Handoff starts with one line: `CONFIRMED: <ids>` (e.g. `CONFIRMED: egress-flood, identity-compromise`).

### 4. Advisor

- Give it the filed hypotheses directly: in `run_agent`, append a line to the Advisor's context listing
  `store.record.hypotheses` (name + verdict + evidence). This is passing state, not deciding for it.
- Order: **first round = `get_runbook` for every hypothesis with verdict `confirmed`/`likely` (plus
  `identity-compromise`), and nothing for ruled-out ones**; containment calls start in round 2 following each runbook's
  Contain order. (Speed is still fine: runbook reads are instant and batched.)
- Replace "state the $ compute impact" with "state the business impact appropriate to the scenario (compute $ for
  cryptojacking, what left and how big for exfiltration, target and duration for a flood)".
- Name the runbooks followed in the final summary.

### 5. Runbooks

Only tighten the **Signals** line of each file to match the table (especially: cryptojacking requires a GPU request;
egress-flood = no GPU + flood logs). Don't restructure them.

## Acceptance (run each twice — temperature 0 should make them stable)

`POST /reset` between runs; drive over HTTP (`/attack/gain-access` then the step). Check `decisions.jsonl` +
the Incident page.

| Scenario | Categories | Hypotheses | Runbooks read (`get_runbook`) |
|---|---|---|---|
| start-miner | cryptojacking (+unauthorized-access) | cryptojacking confirmed; other three ruled out | cryptojacking, identity-compromise — **not** persistence/flood |
| steal-weights | data-exfiltration | data-exfiltration confirmed; cryptojacking ruled out | data-exfiltration, identity-compromise |
| persistence | persistence (+cryptojacking ok — the CronJob mines) | persistence confirmed | persistence (+cryptojacking), identity-compromise |
| ddos | egress-flood | egress-flood confirmed; cryptojacking ruled out | egress-flood, identity-compromise; **no** `mining_impact` call |

Also: no "reached its step limit"; containment still happens; one revoke card per incident. Report the table with
PASS/FAIL and the exact Investigator handoff line for any FAIL. If a scenario still fails after the prompt changes,
report it — don't add code that classifies for the agents (that's a separate decision for the user).

## Also fix in this lane: detection fail-open on "terminating" objects (security review)

`_detect()` currently drops every pod/CronJob that has `metadata.deletion_timestamp` set. An attacker can add a
finalizer or a huge `terminationGracePeriodSeconds` so a pod sits in Terminating while it keeps running — and
detection never sees it again. Keep the original intent (don't re-flag pods the defender just deleted) but fail closed:

- Skip a terminating pod ONLY if it has no `metadata.finalizers` AND
  `now < deletion_timestamp + (deletion_grace_period_seconds or 30) + 30 s slack`. Otherwise evaluate it like any
  other pod (it stays rogue).
- Skip a terminating CronJob only if it has no finalizers; otherwise flag it.
- Leave one runnable check behind (e.g. a small `__main__`/assert-based self-check with fake pod objects: fresh
  delete → skipped; past deadline → flagged; finalizer present → flagged). No real cluster needed for it.
