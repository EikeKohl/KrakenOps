"""In-process pub/sub bus.

Each subscriber gets a bounded asyncio.Queue. Slow consumers don't back up
publishers — when a subscriber's queue is full the message is dropped and a
warning is logged. This is intentional: KrakenOps is local-first, the
producer side (psutil sampler, ingest route) must never stall.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

_log = logging.getLogger("krakenops.realtime.bus")

# Topics defined in CLAUDE.md §5. The bus accepts arbitrary topic names but
# the WS endpoint validates against this set.
TOPICS = ("metrics", "traces", "kanban")

_QUEUE_MAX = 1024


class PubSub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, topics: list[str]) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        for t in topics:
            self._subscribers[t].add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]], topics: list[str]) -> None:
        for t in topics:
            self._subscribers[t].discard(q)

    def publish(self, topic: str, data: Any) -> int:
        """Synchronous publish (uses put_nowait). Returns the number of subscribers reached."""
        msg = {"topic": topic, "ts": time.time_ns(), "data": data}
        delivered = 0
        # Snapshot subscribers; iteration must not be disturbed by a concurrent unsubscribe.
        for q in list(self._subscribers.get(topic, ())):
            try:
                q.put_nowait(msg)
                delivered += 1
            except asyncio.QueueFull:
                _log.warning("dropping %s message for slow subscriber (queue full)", topic)
        return delivered

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, ()))


# Global singleton — one bus per process. The PubSub itself owns no I/O so
# this is safe across asyncio event loops as long as it's used inside one.
BUS = PubSub()
