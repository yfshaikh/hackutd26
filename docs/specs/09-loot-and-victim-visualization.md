# Spec 09 — Watch the loot arrive and the victim get hammered (attacker app only)

**Lane:** attack side. **Files:** `deploy/10-lawfirm.yaml`, `deploy/20-ddos-sink.yaml`, `backend/app/attacks/bodies.py`,
a NEW `backend/app/routes_loot.py` (+ one `include_router` line in `backend/app/main.py`), a NEW
`attacker/src/LootPanel.tsx` (+ the smallest wiring edit in `attacker/src/`). **Do not touch `backend/app/defender.py`,
`k8s.py`, or anything under `console/`** — other lanes are editing them in parallel.

## Hard rules

> Never read, cat, grep, tail, source, or otherwise open `.env` or any
> secrets file, by any means, including via a script or subprocess. This
> also bans unscoped `grep -rn` from a repo root — always scope a grep to a
> directory. If you need a credential, read it from `os.environ` /
> `process.env` at runtime and never print it. If something appears to be
> missing, stop and report it; do not go looking for the value.

- Do not commit. When done, show `git status --short` and a focused `git diff --stat` and stop.
- Exactly ONE backend may run (a singleton lock refuses a second; stop the old one, don't bypass the lock).
- Another session ("Dashboard UI cleanup and redesign") may have uncommitted edits in `attacker/src/` and
  `scratch/hacker-laptop.html`. Run `git status` / `git diff` on those first and don't overwrite its work.

## Goal

Make the attacker's loot and the DDoS victim WATCHABLE live in the attacker app (the "laptop" UI in `attacker/`,
port 5180). When "Steal weights" runs, the attacker watches the model file arrive at the drop site (progress bar, MB
received, then a listing of what's inside the stolen file). When "DDoS" runs, they watch the victim (sink) get hammered
(live connection counter). Do NOT add this to the defender console; the defender can't see inside the attacker's
server in real life.

Repo: `/Users/yusufshaikh/Desktop/Projects/hackutd26`. Cluster is k3s on a Brev VM reached over Tailscale;
`KUBECONFIG=~/.kube/hackutd.yaml`.

## Current state (verify by reading the code first)

- `deploy/10-lawfirm.yaml` defines the `drop` server (namespace `drop-site`, ConfigMap `drop`, `drop.py`). It accepts an
  HTTP PUT, writes the body to `/loot/<name>`, and prints ONE line at the end: `received /contracts-ft-v3.pt <N> bytes`.
- `deploy/20-ddos-sink.yaml` defines `sink` (drop-site). It accepts and closes TCP connections and prints
  `sink accepted <n> connections` every 25.
- `attacks/bodies.py`: `_EXFIL_PY` reads `/weights/contracts-ft-v3.pt` (~288 MB) and PUTs it in one shot (1–2 s, nothing
  to watch). `_FLOOD_PY` is capped at 200 connections / 20 s against `sink.drop-site.svc` (hard-coded).
- The attacker app already streams a transcript over SSE (`GET /attack/stream`; see `backend/app/transcript.py` and
  `attacker/src/api.ts`).

## What to build

1. **drop.py:** while receiving, print progress lines every ~8 MB using a DIFFERENT word, e.g.
   `progress /contracts-ft-v3.pt 48234496/302335262 bytes`. Keep the final `received <path> <N> bytes` line EXACTLY as
   it is — `defender._check_exfil_evidence()` parses the first line containing "received" + the filename and takes the
   first integer as the byte count, so a progress line containing "received" would mark the weights exfiltrated early
   with the wrong size. After the file is written, list the entries inside it with Python's `zipfile` (a `.pt` file is a
   zip archive) and print them, e.g. `entry archive/data/0 4194304 bytes`. NEVER `torch.load` or unpickle the file.
2. **sink.py:** print the count more often (every 5) so the counter moves smoothly.
3. **`_EXFIL_PY`:** throttle the upload to ~15–20 s (fixed-size chunks + short sleep, correct `Content-Length`, e.g. with
   `http.client`). Keep it read-only on the PVC and the target unchanged. (Bonus: a longer-lived exfil pod also gives the
   defender agents a live pod to inspect.)
4. **Backend:** `GET /attack/loot` in the new `routes_loot.py` (SSE or a short poll — match how the attacker app already
   consumes `/attack/stream`). Read the drop and sink pods' recent logs with the existing admin client (see how
   `_check_exfil_evidence` reads the drop log — copy the pattern, don't import from defender). Return
   `{exfil: {bytes, total, done, entries: [...]}, ddos: {connections, running}}`. Attacker endpoints have no sign-in by
   design, so return only counts and entry names, never file contents. Note `GET /attack` and `POST /attack/{step}`
   already exist — `GET /attack/loot` doesn't collide, but register it before any catch-all.
5. **Attacker app:** a "Loot" panel (progress bar + MB counter, then the entry listing when done) and a "Victim" panel
   (climbing connection count) in `attacker/src/LootPanel.tsx`. Both reset when Reset runs (reset already wipes
   `/loot`).

## Safety rules that must stay true

- The DDoS target stays hard-coded to `sink.drop-site.svc`; no arg or config may point it elsewhere. Keep the
  200-connection / 20 s caps.
- `drop` and `sink` stay ClusterIP only: no NodePort, LoadBalancer or external IP.
- Nothing ever sends traffic outside the cluster.

## Applying the cluster changes

After editing the ConfigMaps: `kubectl apply -f deploy/10-lawfirm.yaml -f deploy/20-ddos-sink.yaml`, then
`kubectl -n drop-site rollout restart deploy/drop deploy/sink` (pods don't reload a changed ConfigMap on their own).

## Verify

Start backend, console and attacker app (README "Run it"). Gain access → Steal weights: the bar fills over ~15–20 s and
the entry list appears; the defender console still shows the weights exfiltrated **with the correct byte count**
(Incident page + scope). DDoS: the counter climbs to ~200. Reset: both panels clear.
