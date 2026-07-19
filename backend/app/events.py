"""In-process pub/sub for run events, feeding the SSE endpoint.

History is kept in memory for the process lifetime so an SSE client that
connects mid-run (or reconnects) gets the full trace. Durable history lives
in the run_steps / artifacts tables.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import defaultdict
from typing import Any


class RunEventBus:
    def __init__(self) -> None:
        self._history: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._subscribers: dict[int, list[asyncio.Queue[dict[str, Any] | None]]] = (
            defaultdict(list)
        )
        self._seq = itertools.count(1)

    def emit(self, run_id: int, event_type: str, **payload: Any) -> None:
        event = {
            "seq": next(self._seq),
            "run_id": run_id,
            "type": event_type,
            "ts": time.time(),
            **payload,
        }
        self._history[run_id].append(event)
        for queue in self._subscribers[run_id]:
            queue.put_nowait(event)

    def close(self, run_id: int) -> None:
        """Signal end-of-stream to all subscribers of a finished run."""
        for queue in self._subscribers[run_id]:
            queue.put_nowait(None)

    def subscribe(
        self, run_id: int
    ) -> tuple[list[dict[str, Any]], asyncio.Queue[dict[str, Any] | None]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._subscribers[run_id].append(queue)
        return list(self._history[run_id]), queue

    def unsubscribe(
        self, run_id: int, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        try:
            self._subscribers[run_id].remove(queue)
        except ValueError:
            pass

    def history(self, run_id: int) -> list[dict[str, Any]]:
        return list(self._history[run_id])


bus = RunEventBus()
