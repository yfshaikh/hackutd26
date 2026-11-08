"""In-memory state store + Server-Sent-Events hub.

This is the backend's memory. Nearly the whole demo's state (cluster snapshot,
timeline, assets, incident record, approvals, attack-step progress) lives in one `Store`
object in RAM, and is lost on restart — which is fine for a hackathon demo. The one
exception is history: when an incident is resolved (or a reset banks it), it is copied to
SQLite via `db.py` so past incidents survive a restart. The live store never reads back
from that history.

"Server-Sent Events" (SSE) is a simple one-way stream: the browser opens a long-lived HTTP
connection and the server pushes text lines down it as things happen. That's how the console
and attacker app update live — every time the Store changes, it publish()es an event to every
open connection, instead of the browser having to poll.

Single-process, asyncio. All mutations run on the event loop thread (blocking
k8s calls are pushed to threads but their results are applied back here), so
publishing is a plain, non-locking fan-out to subscriber queues.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from typing import Any, Optional

from . import config, db, notify
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

log = logging.getLogger(__name__)


# --- Attack step state machine --------------------------------------------
# Access is the one gate. Only "gain-access" starts "ready"; the rest are "locked".
# Running gain-access flips ALL four follow-on attacks to "ready" at once (see
# attacks/steps.py), so the operator then picks any of miner / weights / persistence /
# ddos, in any order. The UI greys out locked steps, so only "steal the token" is
# available until it succeeds.
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
        AttackStep(
            id="ddos",
            label="DDoS flood",
            description="Turn the compromised pod into a bounded connection flood against an in-cluster sink.",
            status="locked",
        ),
    ]


class Store:
    """The single in-memory source of truth for the command center. Everything the
    console shows (timeline, assets/scope, approvals, incident record, attack steps,
    cluster snapshot) lives here. Every mutator also publish()es an SSE event so open
    consoles update live. One instance (`store` at the bottom) is shared process-wide."""

    def __init__(self) -> None:
        self.timeline: list[TimelineEntry] = []        # the incident feed (attack/agent/human/system)
        self.assets: dict[str, Asset] = {}             # protected assets + their scope status
        self.approvals: dict[str, Approval] = {}       # human-approval requests the agent raised
        self.record: Optional[IncidentRecord] = None   # the NIST incident record (None until one opens)
        self.attack: dict[str, AttackStep] = {s.id: s for s in _default_attack_steps()}
        self.cluster: Optional[Cluster] = None         # last cluster snapshot (nodes/pods/GPU)
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
        """Fan out an event to all SSE subscribers (thread-safe).

        Mutators may run on a worker thread (blocking k8s calls go through
        asyncio.to_thread), so when we're off the loop we hand the fan-out back to
        it with call_soon_threadsafe — asyncio.Queue is not thread-safe."""
        loop = self._loop
        if loop and loop.is_running():
            try:
                asyncio.get_running_loop()   # on the loop thread? fan out directly
                self._fanout(event)
            except RuntimeError:             # on a worker thread → marshal onto the loop
                loop.call_soon_threadsafe(self._fanout, event)
        else:
            self._fanout(event)

    # ---- snapshot --------------------------------------------------------
    def attack_list(self) -> list[AttackStep]:
        order = ["gain-access", "start-miner", "steal-weights", "persistence", "ddos"]
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
        agent: str | None = None,
        trace_only: bool = False,
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
            agent=agent,
            traceOnly=trace_only or None,
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
        # Page the on-call engineer once, when a pending approval FIRST appears. Later
        # upserts are decisions (status changed) or the paging outcome, so they must not
        # re-page. The call runs on its own thread and swallows its errors: a phone problem
        # never blocks filing the approval or the detection loop.
        first_pending = approval.status == "pending" and approval.id not in self.approvals
        self.approvals[approval.id] = approval
        self.publish({"type": "approval", "approval": approval.model_dump(exclude_none=True)})
        if first_pending:
            notify.page_oncall_soon(approval, self.record)
        return approval

    def set_approval_paging(self, approval_id: str, result: str) -> None:
        """Record how the on-call page went on the approval, if it is still in the live store.

        Deliberately not an upsert: a page can finish after a reset cleared the approvals,
        and re-adding a cleared approval would resurrect it.
        """
        approval = self.approvals.get(approval_id)
        if approval is None:
            return
        approval.paging = result
        self.publish({"type": "approval", "approval": approval.model_dump(exclude_none=True)})

    def set_record(self, record: IncidentRecord | None) -> None:
        self.record = record
        if record is not None and record.status == "resolved":
            self.archive_incident()
        payload = record.model_dump(exclude_none=True) if record else None
        self.publish({"type": "record", "record": payload})

    def archive_incident(self) -> None:
        """Bank the current record + timeline into the history DB (best-effort).

        Called when an incident leaves the live state: `set_record` sees status →
        resolved, or `reset_incident_state` clears it. A history write must never
        break the detection loop, so failures are logged and swallowed.
        """
        if self.record is None:
            return
        try:
            db.archive(self.record, self.timeline)
        except Exception:  # noqa: BLE001
            log.exception("Could not archive incident %s", self.record.id)

    def set_cluster(self, cluster: Cluster) -> None:
        self.cluster = cluster
        self.publish({"type": "cluster", "cluster": cluster.model_dump(exclude_none=True)})

    def set_attack_status(self, step_id: str, status: str) -> None:
        # Drives the state machine: "locked" -> "ready" -> "running" -> "done".
        # attacks.py flips the next step to "ready" as each one finishes.
        if step_id in self.attack:
            self.attack[step_id].status = status

    def publish_attack(self) -> None:
        self.publish(
            {"type": "attack", "attack": [s.model_dump(exclude_none=True) for s in self.attack_list()]}
        )

    def reset_incident_state(self) -> None:
        # Wipe the incident back to a blank slate and relock the attack chain.
        # Bank it first, so a reset doesn't erase the incident from history.
        # NOTE: this empties assets; callers that want scope back must re-seed it
        # (cluster.seed_assets() + upsert_asset), since this does not.
        self.archive_incident()
        self.timeline.clear()
        self.assets.clear()
        self.approvals.clear()
        self.record = None
        for s in _default_attack_steps():
            self.attack[s.id] = s


store = Store()
