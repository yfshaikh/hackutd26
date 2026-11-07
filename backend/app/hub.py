"""In-memory state store + Server-Sent-Events hub.

Single-process, asyncio. All mutations run on the event loop thread (blocking
k8s calls are pushed to threads but their results are applied back here), so
publishing is a plain, non-locking fan-out to subscriber queues.
"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from typing import Any, Optional

from . import config
from .models import (
    Approval,
    Asset,
    AttackStep,
    Cluster,
    IncidentRecord,
    Snapshot,
    TimelineEntry,
    now_iso,
)

GPU_HISTORY_LEN = 90  # ~3 min at one sample / 2 s


def _default_attack_steps() -> list[AttackStep]:
    return [
        AttackStep(
            id="gain-access",
            label="Gain access",
            description="Exploit the exposed notebook and steal its service-account token.",
            status="ready",
        ),
        AttackStep(
            id="start-miner",
            label="Start miner",
            description="Launch a disguised GPU-cryptojacking pod with the stolen token.",
            status="locked",
        ),
        AttackStep(
            id="steal-weights",
            label="Steal weights",
            description="Mount the model-weights volume and exfiltrate contracts-ft-v3.pt.",
            status="locked",
        ),
        AttackStep(
            id="persistence",
            label="Persistence",
            description="Install a CronJob that respawns the miner.",
            status="locked",
        ),
    ]


class Store:
    def __init__(self) -> None:
        self.timeline: list[TimelineEntry] = []
        self.assets: dict[str, Asset] = {}
        self.approvals: dict[str, Approval] = {}
        self.record: Optional[IncidentRecord] = None
        self.attack: dict[str, AttackStep] = {s.id: s for s in _default_attack_steps()}
        self.cluster: Optional[Cluster] = None
        self.gpu_history: deque[float] = deque(maxlen=GPU_HISTORY_LEN)
        self._subs: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ---- loop wiring -----------------------------------------------------
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- subscriptions ---------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _fanout(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def publish(self, event: dict[str, Any]) -> None:
        """Fan out an event to all SSE subscribers (thread-safe)."""
        loop = self._loop
        if loop and loop.is_running():
            try:
                asyncio.get_running_loop()
                self._fanout(event)
            except RuntimeError:
                loop.call_soon_threadsafe(self._fanout, event)
        else:
            self._fanout(event)

    # ---- snapshot --------------------------------------------------------
    def attack_list(self) -> list[AttackStep]:
        order = ["gain-access", "start-miner", "steal-weights", "persistence"]
        return [self.attack[i] for i in order]

    def snapshot(self) -> Snapshot:
        return Snapshot(
            firm=config.FIRM_NAME,
            cluster=self.cluster or Cluster(name="hackutd", nodes=[], pods=[], gpuHistory=[]),
            assets=list(self.assets.values()),
            timeline=self.timeline,
            approvals=list(self.approvals.values()),
            record=self.record,
            attack=self.attack_list(),
        )

    # ---- mutators (each also publishes) ----------------------------------
    def add_timeline(
        self,
        *,
        kind: str,
        actor: str,
        text: str,
        severity: str | None = None,
        autonomy: dict | None = None,
        tool: str | None = None,
        target: str | None = None,
        tool_args: dict | None = None,
        tool_result: str | None = None,
        reasoning: str | None = None,
        pod_logs: str | None = None,
        transcript: list[dict] | None = None,
    ) -> TimelineEntry:
        entry = TimelineEntry(
            id=f"tl-{uuid.uuid4().hex[:10]}",
            ts=now_iso(),
            kind=kind,
            actor=actor,
            text=text,
            severity=severity,
            autonomy=autonomy,
            tool=tool,
            target=target,
            toolArgs=tool_args,
            toolResult=tool_result,
            reasoning=reasoning,
            podLogs=pod_logs,
            transcript=transcript,
        )
        self.timeline.append(entry)
        self.publish({"type": "timeline", "entry": entry.model_dump(exclude_none=True)})
        return entry

    def upsert_asset(self, asset: Asset) -> Asset:
        self.assets[asset.id] = asset
        self.publish({"type": "asset", "asset": asset.model_dump(exclude_none=True)})
        return asset

    def set_asset_status(self, asset_id: str, status: str, note: str | None = None) -> Asset | None:
        asset = self.assets.get(asset_id)
        if not asset:
            return None
        asset.status = status
        asset.statusSince = now_iso()
        if note is not None:
            asset.note = note
        return self.upsert_asset(asset)

    def upsert_approval(self, approval: Approval) -> Approval:
        self.approvals[approval.id] = approval
        self.publish({"type": "approval", "approval": approval.model_dump(exclude_none=True)})
        return approval

    def set_record(self, record: IncidentRecord | None) -> None:
        self.record = record
        payload = record.model_dump(exclude_none=True) if record else None
        self.publish({"type": "record", "record": payload})

    def set_cluster(self, cluster: Cluster) -> None:
        self.cluster = cluster
        self.publish({"type": "cluster", "cluster": cluster.model_dump(exclude_none=True)})

    def set_attack_status(self, step_id: str, status: str) -> None:
        if step_id in self.attack:
            self.attack[step_id].status = status

    def publish_attack(self) -> None:
        self.publish(
            {"type": "attack", "attack": [s.model_dump(exclude_none=True) for s in self.attack_list()]}
        )

    def reset_incident_state(self) -> None:
        self.timeline.clear()
        self.assets.clear()
        self.approvals.clear()
        self.record = None
        for s in _default_attack_steps():
            self.attack[s.id] = s


store = Store()
