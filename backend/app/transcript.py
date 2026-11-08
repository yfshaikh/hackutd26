"""Live attack transcript: the ordered record of what the attacker actually did.

Each entry is {id, ts, step, kind, text, ...extra} where kind is one of
cmd | code | http | output | note. The attacker app streams these over
GET /attack/stream (SSE) and reads history over GET /attack/transcript.

This is a separate feed from the defender console's /events: the console shows
the defender's view, this shows the attacker's own terminal.

In plain terms:
  - Think of this as the attacker's live terminal log. Each attack step calls
    `transcript.emit(kind, text)` to append one line, and the attacker app shows it.
  - The `kind` is just what sort of line it is, so the UI can style it:
      note   = a human explanation ("look for an unauthenticated JupyterLab…")
      code   = the actual Python being sent into the notebook kernel
      http   = a call to the Kubernetes API server (method, url, status)
      output = what came back (printed results, pod logs)
      cmd    = a shell-style command
  - SSE (Server-Sent Events) is a simple one-way stream: the browser opens
    GET /attack/stream and the server keeps pushing new lines down that one
    connection as they happen — no polling. `subscribe()` gives each connected
    viewer its own queue; `emit()` fans every new line out to all of them.
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
        # Push to every subscriber's queue without blocking: a slow/stuck SSE client
        # whose queue is full just drops events rather than stalling the attack.
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def _publish(self, event: dict[str, Any]) -> None:
        # emit() is called from attack steps that run in worker threads (asyncio.to_thread),
        # so we may be off the event loop. asyncio.Queue is not thread-safe, so when we're
        # not already on the loop we marshal the fan-out onto it with call_soon_threadsafe.
        loop = self._loop
        if loop and loop.is_running():
            try:
                asyncio.get_running_loop()   # raises if we're on a worker thread, not the loop
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
            self.entries = self.entries[-MAX_ENTRIES:]  # ring buffer: keep the last 1000 lines
        self._publish({"type": "transcript", "entry": entry})  # live push to the attacker app
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
