# WS-C ledger — evals suite

Append-only, newest on top.

## Status
- State: built + verified offline. The suite runs the 8 scenarios × N × models, scores the
  9 metrics, writes `backend/evals/results.json`, and serves it at `GET /defender/evals`;
  the console has an Evals page. **A live run (`cd backend && uv run python -m evals --runs N`)
  needs a Nemotron key + the cluster + the DDoS sink applied — not yet executed here.**
- Not committed.

## Decisions
- (2026-11-07) Split runner from scorer: `scoring.py` is pure (RunResult -> MetricResult),
  so it's unit-tested without the cluster; `runner.py` does all the live work. Built with
  spec-driven sub-agents: scorer + console page forked in parallel, runner/report/CLI by me.
- (2026-11-07) Drive attacks via `attacks.run_step()` (same entry the HTTP API uses) so the
  harness can sequence steps the UI lock-chain wouldn't allow (e.g. exfil without the miner).
- (2026-11-07) Added `defender.detection_tick()` (one loop iteration) so the harness can step
  the defender synchronously; refactored `detection_loop()` to call it. Clean, no behavior change.
- (2026-11-07) Cost is a flat per-round estimate (real token usage isn't logged yet) — noted
  in `runner.py`. "lightning" model id in `__main__.py` is a guess; override with `--models`.
- (2026-11-07) Scenario 8 (reproducibility) runs the base scenario twice and compares the
  ordered decision-tool sequence; reported in `summary.reproducibility`.

## Changelog
- (2026-11-07) Bugfix (caught in annotation review): `runner._reset()` called
  `cluster.seed_assets()` expecting it to seed the store, but that only RETURNS the list.
  Combined with `store.reset_incident_state()` emptying assets, eval scope wouldn't reset
  between runs (correct_scope would always fail). Now calls `reset_incident_state()` then
  upserts each seeded asset. Re-verified green.
- (2026-11-07) Annotation pass: reading maps/comments across backend + deploy; "Read the
  backend in this order" added to the System Map artifact (v15). No logic change.
- (2026-11-07) Added `backend/evals/`: `model.py` (dataclasses), `scenarios.py` (8 scenarios),
  `scoring.py` + `test_scoring.py` (9 metrics, self-test green), `runner.py` (live runner),
  `report.py` (aggregate -> results.json + table), `__main__.py` (CLI), `__init__.py`.
  `GET /defender/evals` in `routes_defender.py`. `detection_tick()` in `defender.py`.
  Console Evals page (`console/src/pages/Evals.tsx` + types/api/App/TopBar/styles).
  Verified: all modules import, scorer test green, offline scoring->report->json->table
  pipeline green, endpoint registered (401), console typecheck clean. **done (offline);
  live run pending.**
