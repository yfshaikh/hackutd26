# DeepSeek work specs — index

Six specs. Each is self-contained; hand one per chat. **Read the "Read first" files in each spec before coding.**

| # | Spec | Primary files | Lane |
|---|------|---------------|------|
| 01 | [Attacker UI](01-attacker-ui.md) — run-another-attack, grouped Next, collapsible code | `attacker/` | **A** |
| 02 | [Records tab](02-records-tab.md) — incident record → own top-level tab | `console/` | **B** |
| 03 | [Database](03-database.md) — persist past incidents (sqlite) | `backend/` (+`hub.py`) | **C** |
| 04 | [Cartesia paging](04-cartesia-paging.md) — phone on-call on approval | `backend/` (+`hub.py`) | **D** |
| 05 | [Evidence-driven investigation](05-evidence-driven-investigation.md) | `backend/defender.py` | **E** |
| 06 | [Verify-and-reconverge](06-verify-and-reconverge.md) | `backend/defender.py` | **E** |

## How to parallelize (what collides, what doesn't)
- **A (attacker)**, **B (console)**, **E (defender.py)** are fully independent — different file trees. Run them in
  parallel chats freely.
- **05 and 06 both edit `defender.py`** → do them in **ONE chat** (E), 05 then 06, or they'll conflict.
- **03 and 04 both add a hook to `backend/app/hub.py`** (03 → `archive_incident` on resolve; 04 → page on
  `upsert_approval`). Run **C and D in one chat** (or sequence them) so the two small `hub.py` edits don't collide.

**So: up to 4 parallel chats — A, B, E, and (C+D).** `defender.py` is single-writer (lane E only); `hub.py` is
touched only by the C+D chat.

## Global invariants — every chat must preserve these (they were just hard-won)
1. **Agent loop convergence:** keep the **force-answer final round** (tools withheld on the last round so each
   agent writes a handoff/summary) and `temperature=0`. Never bring back "reached its step limit".
2. **Approval idempotency:** keep `_approval_sig` de-dup in `defender.py` — an identical pending action is filed
   once (one `revoke_service_account` card, not two). Spec 04's paging and Spec 06's reconverge both rely on this.
3. **Per-agent tool scope** is enforced in code in `_run_role` — don't loosen it.
4. **Ports / CORS:** backend **:8000**, console **:5173**, attacker **:5180** (backend allows only 5173/5180).
5. **Secrets:** never read, print, or commit `.env`. New keys go in **`.env.example`** only; read via `os.environ`
   at runtime. (This matters most for Spec 04.)
6. **Timeline entry fields** the UI depends on: `tool`, `toolResult`, `reasoning`, `agent`, `traceOnly` — don't rename.
7. Don't block or crash the **detection loop** — anything slow or failable (Cartesia call) runs off-thread and
   swallows its own errors.

## Review + test (Claude, at the end)
After each lane lands, Claude will: read the diff for the invariants above, run `npx tsc --noEmit` (console/attacker),
run the backend self-checks, and **re-run the end-to-end attack stress test** (gain-access → miner / exfil /
persistence / ddos against the live cluster, watching the console converge) to confirm no convergence or
idempotency regressions — the same test that validated the current state.
