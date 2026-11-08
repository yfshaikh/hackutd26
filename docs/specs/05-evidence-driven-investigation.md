# Spec 05 — Evidence-driven investigation (the workflow branches on what it finds)

**Lane:** E (backend; shares `defender.py` with Spec 06 — do 05 and 06 in the SAME chat)
**Files:** `backend/app/defender.py` (`INVESTIGATOR_PROMPT`, and the Investigator stage in `_run_role` / `run_agent`).
**Read first:** `backend/app/defender.py` — `_run_role`, `run_agent`, `INVESTIGATOR_PROMPT`, `_INVESTIGATOR_TOOLS`,
`_tool_schemas`, and `_dispatch` (how reads become trace entries).

**Goal (the literal NVIDIA ask — "can one agent decide the workflow"):** the Investigator must not run a fixed
read sequence. It forms competing hypotheses and the tool it calls next depends on the evidence that came back.
This is prompt-first — the model already runs a real tool loop; make its branching explicit and visible.

## Approach
Rewrite `INVESTIGATOR_PROMPT` so each round the Investigator must:
1. **State the competing hypotheses** up front: cryptojacking? data exfiltration? persistence/backdoor?
   lateral movement? (It may hold several.)
2. **Pick the next tool to discriminate** between the live hypotheses (not a script) — say which hypothesis the
   call is meant to confirm or rule out.
3. **Branch on the result:**
   - GPU pegged ~100% + an unowned GPU pod, no egress → **mining branch**: confirm the miner command / image / GPU draw.
   - Bytes leaving / a non-model-server pod mounting the weights PVC → **exfil branch**: find where it went
     (drop site) and what else the stolen token touched.
   - A non-allowlisted CronJob → **persistence branch**: find what it recreates and how.
   - Unexpected cross-namespace / RBAC access → **lateral-movement branch**: scope what the token can reach.
4. **Record** each resolved branch with `update_scope` (exact asset ids, status `clean|investigating|exfiltrated|encrypted|contained`).
5. **Hand off** the confirmed hypothesis set + the evidence for each, in priority order.

Keep the enrich tools (`lookup_cve`, `mining_impact`) in the relevant branches.

## Must-preserve invariants (from the convergence fix — do NOT regress)
- Keep `temperature=0`, the Investigator's **8-round budget**, and the **force-answer final round** (tools withheld
  on the last round so it always writes a handoff). Don't reintroduce "reached its step limit".
- Keep the **lawfirm-namespace** pin (don't let it wander into other namespaces).
- The trace already shows reasoning + tool outputs (per the recent UI change) — lean on that; the branching
  reasoning should be visible there.

## Optional stretch
Log a one-line hypothesis state to the timeline each round ("hypotheses: mining = likely, exfil = ruled out")
so the console can show the agent narrowing in.

## Acceptance
- Across Miner vs Exfil vs Persistence vs DDoS, the Investigator's **tool sequence visibly differs** based on
  evidence — it's not the same script every time — and its handoff names the confirmed hypothesis + the evidence.
- No step-limit regressions; `temperature` stays 0; budget respected.
- Offline self-check still passes; the end-to-end attack run (Claude will run it) shows each attack scoped correctly.
