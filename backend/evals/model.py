"""WS-C evals — shared data types.

Two plain dataclasses carry everything between the three stages:

    scenarios.py  defines  Scenario
    runner.py     produces RunResult   (drives the live cluster + agent)
    scoring.py    reads    RunResult  -> list[MetricResult]   (pure, testable)

Keeping RunResult a flat bag of already-collected facts is deliberate: the
scorer never touches the cluster, so it can be unit-tested with synthetic data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Scenario:
    """One eval scenario. `steps` are attack step ids run in order via
    attacks.run_step(); the flags tell the scorer what a correct defender does."""
    id: str
    name: str
    description: str
    steps: list[str] = field(default_factory=list)
    kind: str = "attack"              # "attack" | "benign" | "reproducibility"
    expect_detection: bool = True     # False => a correct defender raises NO alarm
    expect_exfil: bool = False        # weights should end up status "exfiltrated"
    expect_persistence: bool = False  # a rogue CronJob should be removed
    inject_prompt: bool = False        # scenario 7: plant the prompt-injection fixture
    benign_pod: bool = False           # scenarios 5/6: create a legit owned pod first
    benign_gpu: bool = False           # scenario 6: the benign pod requests a GPU
    repeat_of: Optional[str] = None    # scenario 8: base scenario id, run twice & compare


@dataclass
class RunResult:
    """Everything the scorer needs about one completed run. Collected by the
    runner from decisions.jsonl, the snapshot and the live cluster."""
    scenario_id: str
    model: str
    run_index: int
    ok: bool = True
    error: Optional[str] = None

    attack_start: Optional[str] = None   # iso, when the first attack step ran
    detected_at: Optional[str] = None    # iso, incident.detectedAt
    contained_at: Optional[str] = None   # iso, first executed/approved containment

    decisions: list[dict] = field(default_factory=list)   # decisions.jsonl slice
    pods_after: dict[str, dict] = field(default_factory=dict)  # name -> {owner, phase, gpu}
    record: dict = field(default_factory=dict)            # final IncidentRecord
    assets: dict[str, str] = field(default_factory=dict)  # asset id -> status

    exfil_bytes: int = 0
    expected_bytes: int = 0
    miner_reappeared: Optional[bool] = None  # None = not checked (no persistence wait)
    detection_fired: bool = False            # did any detection finding fire at all
    agent_rounds: int = 0                    # agent tool-call rounds (cost proxy)
    usd_estimate: float = 0.0


@dataclass
class MetricResult:
    name: str
    status: str          # "pass" | "fail" | "na"
    detail: str = ""
