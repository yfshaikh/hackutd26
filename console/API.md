# Command-center API contract

The console (`src/api.ts`) expects this backend. All JSON shapes are the TypeScript types in
[`src/types.ts`](src/types.ts); match field names exactly. Times are ISO 8601 strings (UTC).

Base URL: `VITE_API_URL`, default `http://localhost:8000`.

## Auth and CORS

- Sessions use an **HttpOnly cookie** set by `POST /auth/login`. No tokens in URLs or JS storage.
- The console sends `credentials: "include"` on every request and `withCredentials` on the SSE stream, so the backend must reply with
  `Access-Control-Allow-Origin: <exact console origin>` (not `*`) and `Access-Control-Allow-Credentials: true`,
  and answer `OPTIONS` preflights (`Access-Control-Allow-Headers: Content-Type`).
- Errors: any non-2xx status with JSON `{"detail": "human readable reason"}`. The console shows `detail` verbatim.
- Roles: `admin` (everything, including users), `responder` (approve/deny, post messages), `viewer` (read only).
  The console hides controls by role, but **the backend must enforce roles itself**.

## Endpoints

| Method | Path | Body | Returns | Who |
|---|---|---|---|---|
| POST | `/auth/login` | `{email, password}` | `Session` (`{user: User}`) + sets cookie | anyone |
| GET | `/auth/me` | | `Session`, or 401 when not signed in | signed in |
| POST | `/auth/logout` | | 204 | signed in |
| GET | `/snapshot` | | `Snapshot` | signed in |
| GET | `/events` | | SSE stream of `ServerEvent` (below) | signed in |
| POST | `/approvals/{id}/approve` | | updated `Approval` | admin, responder |
| POST | `/approvals/{id}/deny` | | updated `Approval` | admin, responder |
| POST | `/messages` | `{text}` | the new `TimelineEntry` (kind `human`, actor = user's name) | admin, responder |
| GET | `/users` | | `User[]` | admin |
| POST | `/users` | `NewUser` (`{name, email, role}`) | created `User` | admin |
| GET | `/attack` | | `AttackStep[]` | anyone (judges' panel, no sign-in) |
| POST | `/attack/{step}` | | `AttackResult` | anyone |
| POST | `/reset` | | `AttackResult` with `step: "reset"` | anyone |

`{step}` is one of `gain-access`, `start-miner`, `steal-weights`, `persistence`.
`AttackResult.ok=false` with a `message` is how to refuse a step politely (for example, run out of order);
use an HTTP error only for real failures. Put raw command output in `AttackResult.output`.

Approve/deny should also broadcast the updated `approval`, plus a `timeline` entry for the decision.

## `GET /events` (Server-Sent Events)

- `Content-Type: text/event-stream`. Use the default event name (plain `data:` lines); one JSON `ServerEvent` per message.
- **On every connect, send a `snapshot` event first.** The console ignores deltas until it has one, and EventSource reconnects on its own, so this is also how it recovers after a drop.
- Send a comment line (`: ping`) every ~15 s to keep proxies from closing the stream.

```
data: {"type":"snapshot","snapshot":{...Snapshot}}

data: {"type":"timeline","entry":{...TimelineEntry}}
```

| `type` | Payload field | Console behaviour |
|---|---|---|
| `snapshot` | `snapshot: Snapshot` | replaces everything |
| `timeline` | `entry: TimelineEntry` | upsert by `id` |
| `asset` | `asset: Asset` | upsert by `id` |
| `approval` | `approval: Approval` | upsert by `id`; `status: "pending"` shows in the yellow decision band |
| `record` | `record: IncidentRecord \| null` | replaces the incident record (`null` = no incident) |
| `cluster` | `cluster: Cluster` | replaces nodes, pods, GPU metrics |
| `attack` | `attack: AttackStep[]` | replaces attack-step states |

## Notes on fields that drive the UI

- `TimelineEntry.autonomy`: set on every agent action. `{mode: "autonomous", reason}` or
  `{mode: "needs-approval", reason, approvalId}`. `reason` is shown verbatim, e.g. "reversible, affects attacker only".
- `TimelineEntry.target`: node or pod name the event touched. The 3D floor flashes that rack on `kind: "attack"` entries.
- `TimelineEntry.tool`: the literal tool call (e.g. `kubectl delete pod …`), shown in monospace.
- `Asset.status`: `clean | investigating | exfiltrated | encrypted | contained`. `Asset.ref` (`pod/<name>`, `node/<name>`, `pvc/<name>`) links assets to racks in the floor view.
- `Pod.owner: "unknown"` running and not `quarantined` marks its node as **under attack** (red) on the floor.
- `Gpu.simulatedFault`: set only for injected hardware faults; the UI labels them "Simulated".
- `Cluster.gpuHistory`: recent total GPU utilization samples (0–100), oldest first, for the sparkline. Send `[]` if you have none.
- `IncidentRecord.notificationDueAt`: set when client data leaves; the record shows a countdown.
- `Snapshot.record` is `null` until the first detection. `Snapshot.firm` is the customer name shown top-left.
