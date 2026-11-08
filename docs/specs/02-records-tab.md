# Spec 02 — Incident Record gets its own top-level tab

**Lane:** B (independent — touches only `console/`)
**Files:** `console/src/App.tsx`, `console/src/components/TopBar.tsx`, new `console/src/pages/IncidentPage.tsx`,
`console/src/pages/CommandCenter.tsx`, `console/src/styles.css`.
**Read first:** `App.tsx` (the `usePath()` route switch), `components/TopBar.tsx` (the `<Link>` nav),
`components/IncidentRecord.tsx`, `components/RecordEditor.tsx`, `components/ScopeBoard.tsx`,
`pages/CommandCenter.tsx` (the `TABS` side panel).

Today the incident record lives in a cramped side tab on the Command Center (`TABS` → `{ id: "record" }`).
Promote it to a proper top-level page like Floor / Evals / Users.

## Changes
- **Route:** add `/record` (label "Incident") to the `usePath()` switch in `App.tsx`, and a `<Link href="/record">Incident</Link>`
  in `TopBar.tsx` (after Evals). The router is the tiny `router.tsx` — follow the existing pattern exactly.
- **New page `pages/IncidentPage.tsx`:** a full-width incident view showing, for the current incident:
  - the record fields (`IncidentRecord` component) — title, status, phase, severity, vector, timestamps;
  - **Actions taken** — the record's `actionsTaken` list, prominent (ts · by · text), the heart of "what happened";
  - **Scope** (`ScopeBoard`);
  - the `RecordEditor` when `user.role === "admin"`.
  - A clean empty state when there is no incident.
- **Command Center:** remove `{ id: "record" }` from `TABS` in `CommandCenter.tsx`; keep `scope` and `war room`.
- **History (graceful degradation):** if `GET /incidents` exists (Spec 03), show a list of past incidents at the
  top (newest first) that loads one into the page on click. If the endpoint 404s / isn't there yet, just show the
  current incident. Don't hard-depend on Spec 03.

## Acceptance
- A top-nav **Incident** tab shows the full current incident (fields + actions taken + scope); admins can edit.
- Command Center no longer shows the record side tab (scope + war room remain).
- `npx tsc --noEmit` is clean; works with and without an open incident.

## Gotchas
- Reuse existing components (`IncidentRecord`, `RecordEditor`, `ScopeBoard`) — don't re-implement them.
- Keep auth gating consistent with the other pages.
- Console runs on **:5173** (CORS).
