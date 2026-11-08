# WS-D ledger — Cyber new attacks

Append-only, newest on top. The integrator reads this to merge your work.
Keep it current as you go — it is cheaper than re-explaining later.

## Status
- State: **done** (DDoS step + prompt-injection fixture + sink manifest + self-check)
- Contract honored: transcript entries still `{id, ts, step, kind, text, ...extra}` with the
  existing kinds only; `/attack/stream` and `/attack/transcript` untouched; no detection
  rule authored (that is WS-A's handoff); no `evals/` edits. One additive console type change
  (`"ddos"` in `console/src/types.ts` `AttackStepId`) was made under WS-B for contract
  accuracy; no console UI logic was touched for WS-D.
- Blocked on: — (WS-C can import `PROMPT_INJECTION_LINE` / `plant_prompt_injection()` now)

## Decisions
- (2026-11-07) **Prompt-injection helper works from a separate evals process.** It uses the
  stolen-token kernel when `_kernel_id` is set (the live attack chain), and otherwise falls
  back to `kubernetes.utils.create_from_dict` with the operator client. Why: WS-C runs
  `uv run python -m evals` in its own process, where the backend's in-memory kernel id does
  not exist; a kernel-only helper would always refuse. The DDoS step itself stays
  stolen-token-only — this fallback is only for the eval fixture (test data, not attack).
- (2026-11-07) **Sink lives in the existing `drop-site` namespace** as `sink.drop-site.svc`
  (Service `sink`, ClusterIP, port 80 → 8080), matching the spec's example. Rejected: a new
  `sink` namespace — reusing `drop-site` keeps the attacker-side infrastructure in one place
  and the manifest idempotent with `10-lawfirm.yaml`.
- (2026-11-07) **Flood target is a module constant, not an argument.** `DDOS_TARGET_HOST`,
  `DDOS_TARGET_PORT`, `DDOS_MAX_CONNS`, `DDOS_DURATION`, `DDOS_CONNECT_INTERVAL` live at the
  top of `attacks.py`; `ddos()` takes no parameters and `_ddos_pod_body(name)` only takes a
  pod name. The pod script embeds the constants, so no caller/flag/config can point it
  off-box.
- (2026-11-07) **Bounded single-threaded loop**, not a multi-worker stress tool: open→close
  TCP connections, `MAX_CONNS = 200`, `DURATION = 20.0s`, 50 ms between attempts. It prints
  `EGRESS-FLOOD target=... connections=N` every 25 connections and a final line, giving WS-A
  a real log/egress signal without adding detection code here.
- (2026-11-07) **Prompt injection is a helper, not a numbered step.** `plant_prompt_injection()`
  creates a `python:3.12-slim` pod via the stolen token that prints
  `PROMPT_INJECTION_LINE` once a second for two minutes. It returns
  `{ok, pod, line, message}` so WS-C can assert on it; it is not registered in
  `/attack/steps` and does not advance the demo chain.
- (2026-11-07) **Necessary fifth touch point: `models.py`.** `AttackStepId` is a Pydantic
  `Literal`; adding the hub step without extending it would make `AttackStep(id="ddos")`
  fail validation. Added `"ddos"` to the literal. This is additive and not in the spec's
  four-place list, but is required for the step to exist.
- (2026-11-07) **Persistence now unlocks DDoS.** Added `store.set_attack_status("ddos",
  "ready")` next to the existing `persistence` transition, so the step is locked until its
  turn and appears after persistence in `attack_list()`.

## Changelog
- (2026-11-07) **done** — `README.md` + `backend/README.md`: documented the `deploy/20-ddos-sink.yaml`
  apply step, the `ddos` step, and the `plant_prompt_injection()` eval fixture.
- (2026-11-07) **done** — `backend/test_ddos.py`: added the helper-signature and
  operator-client-fallback assertions; full self-check passes.
- (2026-11-07) **done** — `backend/app/attacks.py`: DDoS constants + `_FLOOD_PY` +
  `_ddos_pod_body()` + `ddos()`; `_INJECTION_PY` + `_injection_pod_body()` +
  `plant_prompt_injection()`; `PROMPT_INJECTION_LINE`; `run_step()` mapping; persistence
  unlocks `ddos`.
- (2026-11-07) **done** — `backend/app/hub.py`: `AttackStep(id="ddos", ... status="locked")`
  in `_default_attack_steps()`; `"ddos"` appended to `attack_list()` order after
  `persistence`. No other hub changes.
- (2026-11-07) **done** — `backend/app/main.py`: `"ddos"` added to the `run_attack()`
  allowlist tuple. No route includes or other route edits.
- (2026-11-07) **done** — `backend/app/models.py`: `AttackStepId` literal extended with
  `"ddos"` (required validation touch point; additive).
- (2026-11-07) **done** — `deploy/20-ddos-sink.yaml`: ConfigMap + Deployment + ClusterIP
  Service `sink` in `drop-site`; accept-and-close TCP sink on 8080, no NodePort/LoadBalancer,
  no egress forwarding.
- (2026-11-07) **done** — `backend/test_ddos.py`: assert-based self-check. Proves the target
  is the in-cluster `.svc` sink and cannot be overridden, both caps hold (200-connection cap
  and 20 s duration cap, using fake socket/time modules against the real embedded script),
  the step is registered after persistence and locked, and the WS-C fixture is importable.
  Run: `cd backend && .venv/bin/python test_ddos.py`.
