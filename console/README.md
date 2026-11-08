# Command center console

The dashboard for the HackUTD 2026 attacker-vs-defender project: live timeline, ranked
approvals, scope board, full NIST SP 800-61 incident record with PDF export, breach-deadline
countdowns, people chat, roles, cluster view (2D list and 3D floor), user admin, and the
attacker workstation. Vite + React + TypeScript; the only runtime dependencies are React,
three.js (lazy-loaded for the 3D floor) and self-hosted fonts, so the console makes no
third-party network requests.

It shows **only real data from the backend**. There is no mock. With no backend running you
get designed "Not connected to the command center at …" states on every screen.

## Run it

```bash
cd console
npm install
npm run dev          # http://localhost:5173
```

Point it at the backend (default `http://localhost:8000`):

```bash
VITE_API_URL=http://<command-center-host>:8000 npm run dev
```

or copy `.env.example` to `.env.local` and set `VITE_API_URL` there.

`npm run build` type-checks and writes `dist/`; `npm run preview` serves the build.

## Routes

| Route | Who | What |
|---|---|---|
| `/` | signed in | Operator console: decision band, client/operator framing, scope, cluster, timeline, incident record + people chat |
| `/floor` | signed in | Full-screen 3D data-center floor |
| `/users` | admin | Add users with a role, change existing roles, list who has access |
| `/attack` | anyone | Redirects to the attacker workstation (5 steps and Reset, no sign-in by design) |

Anything else redirects to `/`. Not signed in shows the sign-in screen.

## How it's wired

```
SSE GET /events ──► store.ts (reducer) ──► context.tsx (LiveProvider) ──► components
REST (approve, deny, messages, users, attack, reset) ◄── api.ts ◄── components
```

- `src/api.ts` is the only file that talks to the network. Every function is typed against `src/types.ts`.
- `subscribe()` opens one EventSource. The server sends a `snapshot` first, then deltas; `store.ts` upserts them.
- Responses from actions (an approved `Approval`, a sent `TimelineEntry`) are applied locally right away via `apply()`, then confirmed by the stream.
- The backend contract (endpoints, SSE events, CORS, roles) is in [API.md](API.md).

## File map

| File | What it does |
|---|---|
| `index.html` | Page shell, `no-referrer` policy |
| `vite.config.ts` | Vite + React plugin, dev port 5173 |
| `.env.example` | Documents `VITE_API_URL` |
| `API.md` | Backend contract |
| `src/types.ts` | All shared types: snapshot, events, assets, approvals, record, users, attack steps |
| `src/api.ts` | REST calls, SSE `subscribe()`, `ApiError` (network vs HTTP) |
| `src/store.ts` | Reduces server events into live state; tracks connection and last attack |
| `src/context.tsx` | `LiveProvider` (one SSE connection) and `SessionProvider` (sign-in via `/auth/me`) |
| `src/router.tsx` | Tiny pathname router and `Link` |
| `src/labels.ts` | Status, severity, phase and role wording and colours in one place |
| `src/format.ts` | Clock, date, "x ago", countdown formatting |
| `src/hooks.ts` | `useNow`, `useReducedMotion` |
| `src/theme.ts` | Light / dark / system toggle |
| `src/styles.css` | Design tokens (both themes) and all styles |
| `src/main.tsx` | Entry: fonts, theme, mount |
| `src/App.tsx` | Routes and sign-in gate; lazy-loads the floor page |
| `src/components/TopBar.tsx` | Firm, nav, NIST phase track, incident status, connection, theme, user |
| `src/agents.ts` | The six actors (attacker, cluster, detector, Sentinel, responders, executor), their mascots, and which one each timeline entry belongs to |
| `src/components/AgentMap.tsx` | Node map of the actors with live state; click a node to filter the timeline |
| `src/components/DecisionBand.tsx` | "What do I do now": compact amber list of ranked decisions (click for reasoning), otherwise a one-line status plus the NIST phase track |
| `src/components/Timeline.tsx` | Unified feed, one line per event with the actor's mascot; click a row for tool call, autonomy reason and full detail |
| `src/components/ScopeBoard.tsx` | Per-asset status, worst first, with tally |
| `src/components/IncidentRecord.tsx` | Full NIST SP 800-61 record, live breach clocks, PDF export, edit toggle |
| `src/components/RecordEditor.tsx` | Human editor for the NIST fields and breach deadlines |
| `src/components/BreachCountdown.tsx` | Live second-by-second notification countdowns |
| `src/components/Chat.tsx` | Person-to-person incident chat (GET/POST `/messages` + live SSE) |
| `src/components/Framing.tsx` | Client (law firm) vs operator (NMC) framing + compromise-resilience |
| `src/components/ClusterView.tsx` | 2D nodes / GPUs / pods with sparkline; toggle to 3D |
| `src/components/NodeDetail.tsx` | Detail drawer for a node or GPU, shared by 2D and 3D |
| `src/components/Empty.tsx` | Empty, connecting and disconnected states |
| `src/components/Status.tsx` | Asset, severity and health chips |
| `src/floor/Floor3D.tsx` | three.js room: one rack per node, glowing GPU slots, pod sleds, quarantine cages, cordon rings, attack flash |
| `src/pages/CommandCenter.tsx` | Main dashboard layout |
| `src/pages/FloorPage.tsx` | `/floor` |
| `src/pages/Users.tsx` | `/users` admin page |
| `src/pages/Login.tsx` | Sign-in, with backend-offline notice |
| `src/pages/AttackPanel.tsx` | `/attack` judges' panel |

## Swapping in the real backend

There is no mock to remove: implement [API.md](API.md) and set `VITE_API_URL`. Checklist:

1. Serve the endpoints and the `/events` SSE stream; send a `snapshot` on connect.
2. CORS with credentials for the console's exact origin.
3. Session cookie (HttpOnly, `SameSite=Lax` if same site, otherwise `SameSite=None; Secure`).
4. Enforce roles server-side.
5. Emit `target` on attack timeline entries so the 3D floor flashes the right rack.

To use WebSockets instead of SSE, change only `subscribe()` in `src/api.ts`; it must keep calling
`onEvent(ServerEvent)` and `onConnection(state)`.

## Design notes

- Styled after HackUTD 2026 Zero Day: near-black night city, electric purple `#7828FF`, lavender, notched buttons, italic Chakra Petch headings. Amber appears **only** when a human decision is waiting.
- Mascot art in `public/mascots/` is HackUTD's (cropped from zeroday.hackutd.co) and is used for the HackUTD demo only.
- Main page: decisions on top, agent map, then the timeline beside a tabbed Scope / Cluster / Record / Chat column.
- Status is always colour + glyph + word (▲ exfiltrated, ■ encrypted, ◐ investigating, ◆ contained, ● clean).
- Type: Chakra Petch for headings, Atkinson Hyperlegible Next (built for legibility) for UI; IBM Plex Mono only for Kubernetes names and tool calls.
- `prefers-reduced-motion` disables CSS transitions and the 3D pulse/flash animation.
