# Spec 04 — Phone the on-call engineer via Cartesia when a human approval is needed

**Lane:** D (backend; shares `hub.py` lightly with Spec 03 — run C and D in the same chat, or sequence them)
**Files:** new `backend/app/notify.py`, `backend/app/hub.py` (fire the page on a new pending approval),
`backend/app/config.py` (env reads), `.env.example` (document new keys), optional small console paging toggle.
**Authoritative reference (copy the pattern):** `/Users/yusufshaikh/Desktop/Projects/nmc/agent-platform/api/gpus.py`
— functions `page()`, `spoken()`, `claim_page_slot()`, `oncall_phone()`, and the constant
`CARTESIA_CALLS = "https://api.cartesia.ai/agents/calls"`.

When an action needs human approval, place **one** outbound call to the on-call engineer with a spoken summary.
Cartesia does the voice + telephony via its agents/calls API.

## The call (mirror the reference exactly)
```
POST https://api.cartesia.ai/agents/calls
headers: { "X-API-Key": CARTESIA_API_KEY, "Cartesia-Version": "2026-08-14" }
body: {
  "from_number_id": CARTESIA_FROM_NUMBER_ID,
  "agent_id": CARTESIA_PAGER_AGENT_ID,
  "ringing_timeout_seconds": 45,
  "outbound_calls": [{ "to_number": ONCALL_PHONE, "dynamic_variables": {...} }]
}
```
Response: the call id is `response.json()["calls"][0]["agent_call_id"]`.

`dynamic_variables` (every value passed through `spoken()` first):
- `action` — the approval's action in plain words (e.g. "revoke the notebook service account token"),
- `rationale` — why a human is needed (the approval's `rationale` / `policyReason`),
- `impact` — the approval's `impact`,
- `incident` — the record title + CVE vector,
- `severity` — the incident severity.

## Trigger (keep it OUT of defender.py)
- Hook in **`store.upsert_approval`** (`hub.py`): when an approval with `status == "pending"` is **first** added,
  call `notify.page_oncall(approval, store.record)` on a **background thread** (never block the request).
- Record the outcome back onto the approval/timeline: `"call placed: <agent_call_id>"`, `"call failed: <type>"`,
  or `"not called: <reason>"`.

## Idempotency & rate limit
- The approval de-dup (`_approval_sig` in `defender.py`) already guarantees one approval per distinct action →
  one call. **Additionally**: guard per-approval (never page the same approval id twice) **and** a global cooldown
  `PAGE_EVERY_SECONDS = 120` (mirror `claim_page_slot`: at most one call per window, even if several approvals fire).

## Config / toggle
- `PAGING_ON` (env, default **false**) — when off, record `"not called: paging off"` and return.
- Keys read via `os.environ` at runtime. **Add to `.env.example` only** (never edit `.env`):
  ```
  CARTESIA_API_KEY=
  CARTESIA_PAGER_AGENT_ID=
  CARTESIA_FROM_NUMBER_ID=
  ONCALL_PHONE=+15125551234
  PAGING_ON=false
  ```
- If any required key is missing → `"not called: paging isn't set up"`, never crash.

## SECURITY (do not skip — this bit the prior project)
- The summary text comes from the **Advisor's output**, which can quote **attacker-controlled pod logs** →
  prompt injection could reach the phone call. Run **all** spoken text through `spoken()` (copy it): strip
  markdown/links, remove phone-number-like digit runs, say units aloud, cap length.
- The Cartesia pager agent is **talk-only** — it has no path back into the backend and cannot approve or change
  anything. Nothing said on the call can act.
- **Never log or show the phone number**, and never store Cartesia's raw error text (it can echo the number back).

## Acceptance
- With keys set + `PAGING_ON=true`, a needs-approval action places exactly one call; the timeline shows
  `"call placed: <id>"`. A second identical (de-duped) approval does **not** re-call; a burst within 120s → one call.
- With keys unset or paging off → graceful `"not called: ..."`, no crash, detection loop unaffected.
- The phone number never appears in logs or UI; injected log text can't reach the call unsanitized.

## Gotchas
- Do the HTTP call off the request path (thread), 30s timeout, catch every exception — a paging failure must never
  break detection or the approval flow.
- Never read or commit `.env`; document keys in `.env.example`.
