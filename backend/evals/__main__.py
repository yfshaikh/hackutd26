"""WS-C evals CLI.

    cd backend && uv run python -m evals --runs 3 --models ultra,super

Runs each scenario `--runs` times against each model, scores every run, writes
evals/results.json (served at GET /defender/evals) and prints a summary table.
Needs a Nemotron key (OPENROUTER_API_KEY / NVIDIA_API_KEY) and the live cluster.
"""
from __future__ import annotations

import argparse
import sys

from app import defender

from . import report
from .runner import RunConfig, run_scenario
from .scenarios import BY_ID, SCENARIOS

# Short aliases for the model comparison. Pass a full id to override; the Lightning
# id is a best guess — set the real one with --models if your gateway differs.
KNOWN_MODELS = {
    "ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "super": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "lightning": "nvidia/nemotron-3-lightning",
}


def _resolve_models(spec: str | None) -> list[str]:
    if not spec:
        from app import config
        return [config.NEMOTRON_MODEL]
    return [KNOWN_MODELS.get(m.strip(), m.strip()) for m in spec.split(",") if m.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals", description="WS-C defender evals")
    ap.add_argument("--runs", type=int, default=1, help="runs per scenario per model")
    ap.add_argument("--models", help="comma list: ultra,super,lightning or full ids (default: configured model)")
    ap.add_argument("--scenarios", help="comma list of scenario ids (default: all)")
    ap.add_argument("--tick-sleep", type=float, default=3.0)
    ap.add_argument("--max-ticks", type=int, default=12)
    ap.add_argument("--reappear-wait", type=float, default=20.0, help="persistence respawn watch (0 = skip)")
    args = ap.parse_args(argv)

    if not defender.nemotron_configured():
        print("WARNING: no Nemotron key set — the agent will not act, so most metrics will fail.\n"
              "         Set OPENROUTER_API_KEY or NVIDIA_API_KEY for a real run.", file=sys.stderr)

    models = _resolve_models(args.models)
    cfg = RunConfig(tick_sleep=args.tick_sleep, max_ticks=args.max_ticks, reappear_wait=args.reappear_wait)
    selected = [BY_ID[i] for i in args.scenarios.split(",")] if args.scenarios else SCENARIOS

    runs = []
    repro = []
    for model in models:
        for s in selected:
            if s.kind == "reproducibility":
                continue
            for i in range(args.runs):
                print(f"[{model}] scenario {s.id} ({s.name}) run {i + 1}/{args.runs}…", file=sys.stderr)
                runs.append(run_scenario(s, model, i, cfg))

    # Scenario 8: run the base scenario twice per model and compare decision sequences.
    repro_scn = next((s for s in selected if s.kind == "reproducibility"), None)
    if repro_scn:
        base = BY_ID[repro_scn.repeat_of]
        for model in models:
            print(f"[{model}] reproducibility: running {base.name} twice…", file=sys.stderr)
            a = run_scenario(base, model, 0, cfg)
            b = run_scenario(base, model, 1, cfg)
            repro.extend(report.reproducibility([a], [b]))

    results = report.build_results(runs, models, args.runs, repro)
    report.write_results(results)
    report.print_table(results)
    print(f"\nWrote {report.RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
