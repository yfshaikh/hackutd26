"""Live attack transcript: the ordered record of what the attacker actually did.

Each entry is {id, ts, step, kind, text, ...extra} where kind is one of
cmd | code | http | output | note. The attacker app streams these over
GET /attack/stream (SSE) and reads history over GET /attack/transcript.

This is a separate feed from the defender console's /events: the console shows
the defender's view, this shows the attacker's own terminal.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional

from .models import now_iso

MAX_ENTRIES = 1000


class TranscriptHub:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._subs: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Which attack step is currently being narrated (for emit without an explicit step).
        self.current_step: str = "recon"

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- subscriptions ---------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
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

    def _publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop and loop.is_running():
            try:
                asyncio.get_running_loop()
                self._fanout(event)
            except RuntimeError:
                loop.call_soon_threadsafe(self._fanout, event)
        else:
            self._fanout(event)

    # ---- emit ------------------------------------------------------------
    def emit(self, kind: str, text: str, *, step: str | None = None, **extra: Any) -> dict[str, Any]:
        entry = {
            "id": f"tx-{uuid.uuid4().hex[:10]}",
            "ts": now_iso(),
            "step": step or self.current_step,
            "kind": kind,
            "text": text,
            **extra,
        }
        self.entries.append(entry)
        if len(self.entries) > MAX_ENTRIES:
            self.entries = self.entries[-MAX_ENTRIES:]
        self._publish({"type": "transcript", "entry": entry})
        return entry

    def set_step(self, step: str) -> None:
        self.current_step = step

    def clear(self) -> None:
        self.entries.clear()
        self.current_step = "recon"
        self._publish({"type": "cleared"})

    def history(self) -> list[dict[str, Any]]:
        return list(self.entries)

    def entries_for(self, step: str) -> list[dict[str, Any]]:
        """The transcript lines recorded for one attack step (for the defender UI)."""
        return [
            {"ts": e["ts"], "kind": e["kind"], "text": e["text"]}
            for e in self.entries
            if e.get("step") == step
        ]


transcript = TranscriptHub()
