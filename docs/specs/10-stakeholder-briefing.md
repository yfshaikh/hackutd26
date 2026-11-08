# Spec 10 — Stakeholder briefing page (plain-English dashboard + war room)

**Lane:** console UI. **Files:** NEW `console/src/pages/Briefing.tsx`, NEW `console/src/plain.ts`,
`console/src/components/Chat.tsx`, `console/src/pages/CommandCenter.tsx`, `console/src/App.tsx`,
`console/src/components/TopBar.tsx`, and an appended section at the END of `console/src/styles.css`.
**No backend changes** — other lanes are editing `backend/` in parallel. Everything here is derived from the existing
live snapshot (`useLive()`), approvals API and messages API.

## Hard rules

> Never read, cat, grep, tail, source, or otherwise open `.env` or any
> secrets file, by any means, including via a script or subprocess. This
> also bans unscoped `grep -rn` from a repo root — always scope a grep to a
> directory. If you need a credential, read it from `os.environ` /
> `process.env` at runtime and never print it. If something appears to be
> missing, stop and report it; do not go looking for the value.

- Do not commit. Report `git status --short` + `git diff --stat` and stop.
- Don't restyle existing pages; append new CSS in its own clearly-commented section and reuse the existing tokens
  (`--panel`, `--accent`, `--exfil`, `--clean`, `.chip`, `.btn`, `.panel` …).

## Why (the Winstead sponsor's brief)

- "The dashboard is intentionally meant for **non-tech-inclined stakeholders** — easy to digest and understand."
- "**Real-time communication** … stakeholders need to communicate and coordinate over the issue." Between real people;
  a full messaging platform is out of scope — they care about the **presentation**.
- "Assume the attacker can see normal comms … phones are down, email is sporadic. Nobody has information."

Our console already runs out-of-band (off the attacked cluster). Today the people-facing parts are buried: the war
room is a small side tab, and the command center speaks in pods and tool calls. This page is the **partners'
front door**; the command center stays the NMC operators' technical view.

## The page: `/briefing`, top-bar label "Briefing" (place it first, before "Command center")

Reading order, top to bottom on the left; the war room fills the right column (stacks on mobile):

1. **Status headline** — one big sentence + one supporting line, from `plain.ts → headline(snapshot)`:
   - no record: "All clear. No active incident."
   - open, nothing contained: "We are responding to an active attack on the firm's AI systems."
   - contained / eradication: "The attack is contained. Cleanup is underway."
   - resolved: "Resolved. The incident is closed."
   Supporting line: time since detection + "N decisions need you" when approvals are pending.
2. **Comms status strip** — three pills: `Email — unreliable`, `Phone lines — down`, `This console — secure, off the
   firm's network`. Static (it's the sponsor's stated scenario). One sentence under it: "Use this page to coordinate.
   Assume the attacker can read normal email."
3. **What we need from you** — each pending approval in plain words, with Approve / Deny buttons for roles that can
   approve (`canAct` in `labels.ts`, same as `DecisionBand.tsx`; reuse `approve`/`deny` from `api.ts`). Map tool names to plain actions in
   `plain.ts` (e.g. `revoke_service_account` → "Cut off the stolen login the attacker is using"; show `approval.impact`
   as "What this means for the firm"). Never show the raw `revoke_service_account()` string here.
4. **Deadlines** — reuse `BreachCountdown` with a one-line explanation ("Clients must be notified within 72 hours of
   their data leaving the firm").
5. **What's affected** — each asset from `snapshot.assets` as a plain row: its name + a plain status ("Stolen", "Locked",
   "Being checked", "Safe", "Secured") — map `AssetStatus` in `plain.ts`. No pod/PVC names.
6. **Plain-English updates** — a feed derived from `snapshot.timeline` by `plain.ts → plainUpdate(entry)`, which returns
   a sentence or `null` (skip). Rules: skip `traceOnly`, skip tool reads, skip `kind: "attack"` (stakeholders shouldn't
   see the attacker's terminal), skip handoffs. Keep and translate: detector findings ("We spotted unknown software
   running on the firm's AI servers"), executor actions ("We shut down the attacker's program"), approval requests,
   human approvals/denials, drop-site/exfil evidence ("Confidential model files were copied out of the firm"), verify
   "Confirmed: all rogue workloads cleared" ("We checked again: the attacker's programs are gone"), record phase changes.
   Each item: time + sentence + a small severity dot. Also link "Full technical record →" to `/record`.
7. **War room (right column)** — move the existing `Chat` here, full height. Presentation upgrades (UI only):
   - each message shows the sender's name **and role label** (`ROLE` in `labels.ts`), grouped consecutive messages;
   - `@name` mentions highlighted; your own messages right-aligned;
   - a small roster header listing everyone who has posted + you, with a "here now" dot for you;
   - quick-reply chips under the box ("On it", "Need more info", "Approved on my side", "Calling the client") that fill
     the input;
   - plain-English agent updates (from item 6) can interleave as distinct "Update from the response team" cards so the
     conversation and the facts sit side by side — keep them visually different from people's messages.

## Other edits

- `CommandCenter.tsx`: remove the War room tab (the side panel becomes just the Scope board, no tab strip).
- Nothing else in the command center changes.

## Writing rules (this is the point of the page)

- No jargon: never "pod", "PVC", "namespace", "RBAC", "service account", "CronJob", tool names, or CVE ids in the main
  text. Say "the firm's AI servers", "the stolen login", "a hidden scheduled task", "the client contract model".
- Short sentences, sentence case, active voice. A managing partner should understand every line in one read.
- Put all the mapping tables in `plain.ts` so wording is reviewable in one place.

## Verify

Run backend + console (README "Run it"), sign in, open `/briefing`:
- with no incident: the all-clear headline, empty states that say what will appear;
- `POST /attack/gain-access` then `/attack/start-miner`: headline changes, updates stream in plain English, the revoke
  decision appears with Approve/Deny; approving it updates the feed;
- `/attack/steal-weights`: the deadline appears and the model asset reads "Stolen";
- post a chat message from two different signed-in roles (create a second user on `/users` if needed): both appear live
  with role labels;
- 375 px wide: single column, no horizontal scroll;
- `npx tsc --noEmit` clean.
