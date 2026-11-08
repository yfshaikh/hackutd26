# Handoff spec — annotate + organize the backend for readability

**Hand this whole file to the implementer. Goal: make the backend understandable to
someone reading it cold, without changing what it does.**

## Context (read first)

This is a sanctioned HackUTD 2026 security exercise on a GPU box the user rents and
controls: a simulated attacker-vs-defender incident-response demo on k3s. The backend
(`backend/app/`) runs the victim cluster's attack chain and the Nemotron defender; the
`deploy/` manifests define the cluster. The user wants to **understand how the backend
works** by reading it. Your job is comments + light, safe reorganization + a reading-order
in the system-map artifact. **Backend only** — `console/` (the React frontend) is out of
scope.

## Hard rule: behavior-preserving

This is a readability pass, **not** a refactor of behavior. No logic changes, no new
features, no dependency changes. After every file move or edit, prove nothing broke:

```
cd backend && PYTHONPATH=. uv run python -c "import app.main; print('imports OK')"
cd backend && PYTHONPATH=. uv run python test_ddos.py        # WS-D self-check must pass
```

If either fails, fix it before continuing. Do the whole thing as its own commit(s),
separate from any feature work. **Never append a `Co-Authored-By` trailer.**

> Never read, cat, grep, tail, source, or otherwise open `.env` or any secrets file, by any
> means, including via a script or subprocess. This also bans unscoped `grep -rn` from a repo
> root — always scope a grep to a directory. If you need a credential, read it from
> `os.environ` / `process.env` at runtime and never print it. If something appears to be
> missing, stop and report it; do not go looking for the value.

## Task 1 — comments (the priority)

Make each backend file read top-to-bottom. For every module in `backend/app/` and every
manifest in `deploy/`:

- **Module docstring**: what this file is, where it sits in the system, what calls it.
- **Section banners**: group related functions under a one-line `# --- heading ---`.
- **Inline comments on the non-obvious bits only** — not narration of obvious code. The
  parts that genuinely need explaining:
  - `defender.py`: the autonomy policy (`classify`), the read-only vs executor client split,
    why detection/telemetry stays on `admin`, the runbook table, how the Nemotron tool loop
    gates every call, the metrics derivation.
  - `k8s.py`: the three identities (admin / read-only / executor), in-memory TokenRequest
    minting, the admin fallback.
  - `attacks.py`: each of the 5 steps, the stolen-token path, why the DDoS target is
    hard-coded in-cluster, the transcript schema.
  - `hub.py`: the Store (single source of truth) and the attack step state machine.
  - `deploy/*.yaml`: a header comment per manifest — what it creates and why (several
    already have this; bring the rest up to the same bar, especially `10-lawfirm.yaml`).

Comment the **why**, not the **what**. A good test: could a new teammate explain the SA
split or the autonomy gate after reading the file? If not, add the missing comment.

## Task 2 — light, safe reorganization (only where it clearly helps)

Two files are long enough to be hard to navigate: `defender.py` (~860 lines) and
`attacks.py` (~850). Breaking them up is welcome **only if** import paths stay stable and
the checks above stay green. Prefer the lowest-risk option that helps:

- **Lowest risk (do this if unsure):** keep the files, add clear section banners + a
  "map" comment at the top listing the sections in order. No moves.
- **Higher value (do only if confident):** split into a package, keeping the public import
  path identical via re-exports. e.g. `defender.py` → `defender/` package with
  `detection.py`, `policy.py`, `tools.py`, `agent.py`, `metrics.py`, and a `__init__.py`
  that re-exports the names the rest of the app imports (`detection_loop`, `run_agent`,
  `metrics`, `classify`, `reset_detection_state`, …) so `from .defender import X` still
  works everywhere. Same idea for `attacks.py` (steps vs pod-bodies vs helpers), and
  `main.py` routes could move to `app/routes/`.

Rules for any split: change nothing but file boundaries and imports; re-export every name
that was importable before; run the two checks after each move; one file at a time. If a
split gets risky near the demo, stop and fall back to banners + comments — readability
without breakage beats a clean tree that doesn't import.

## Task 3 — "reading order" in the system-map artifact

Add a section to `docs/system-map.html` that tells a newcomer which backend files to read,
in order, to understand the system. Add it as a new `<details>` block (match the existing
ones — there's already a `QA` and a `REAL` array pattern you can copy). Suggested order,
each with a one-line "why":

1. `backend/app/main.py` — the entrypoint: routes + the background loops.
2. `backend/app/config.py` — all the knobs and names in one place.
3. `backend/app/hub.py` — the Store: the single in-memory source of truth.
4. `backend/app/k8s.py` — the three cluster identities and how tokens are minted.
5. `backend/app/attacks.py` — the 5 attack steps (what the attacker does).
6. `backend/app/defender.py` — detection → policy → tools → agent → metrics.
7. `backend/app/routes_incident.py` / `routes_defender.py` — the dashboard + metrics APIs.
8. `deploy/*.yaml` — the cluster itself (lawfirm workloads, GPU plugin, RBAC, sink).

Leave the HTML valid and themed like the rest of the page. The user (or Claude) will
republish the artifact after your edit — you only change the HTML source.

## Done when

- Every `backend/app/` module and `deploy/` manifest has a clear docstring/header and
  comments on the non-obvious parts.
- Any file split keeps `import app.main` and `test_ddos.py` green, with stable import paths.
- `docs/system-map.html` has the reading-order section.
- One focused commit (or a small series), no behavior change.
- Log what you did in `docs/ledger/annotate-reorg.md` (status / decisions / changelog,
  newest on top) — especially any file you split and the re-exports you added.
