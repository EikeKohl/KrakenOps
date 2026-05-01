"""PubSub bus: subscribe, publish, multi-topic fan-out, slow-consumer drop."""

from __future__ import annotations

import asyncio

import pytest

from app.realtime.bus import PubSub


async def test_publish_delivers_to_subscriber() -> None:
    bus = PubSub()
    q = bus.subscribe(["metrics"])

    delivered = bus.publish("metrics", {"cpu_pct": 12.3})
    assert delivered == 1

    msg = await asyncio.wait_for(q.get(), timeout=0.5)
    assert msg["topic"] == "metrics"
    assert msg["data"] == {"cpu_pct": 12.3}
    assert isinstance(msg["ts"], int)


async def test_no_subscribers_returns_zero() -> None:
    bus = PubSub()
    assert bus.publish("metrics", {}) == 0


async def test_unsubscribe_stops_delivery() -> None:
    bus = PubSub()
    q = bus.subscribe(["traces"])
    bus.unsubscribe(q, ["traces"])
    bus.publish("traces", {"x": 1})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), timeout=0.1)


async def test_multi_topic_subscriber_receives_both() -> None:
    bus = PubSub()
    q = bus.subscribe(["metrics", "traces"])
    bus.publish("metrics", {"cpu_pct": 1.0})
    bus.publish("traces", {"name": "span"})

    received_topics = set()
    for _ in range(2):
        msg = await asyncio.wait_for(q.get(), timeout=0.5)
        received_topics.add(msg["topic"])
    assert received_topics == {"metrics", "traces"}


async def test_full_queue_drops_message() -> None:
    bus = PubSub()
    bus.subscribe(["metrics"])
    # Saturate the queue (maxsize is 1024).
    for i in range(1024):
        delivered = bus.publish("metrics", {"i": i})
        assert delivered == 1
    # 1025th publish: queue full → drop, but no exception.
    delivered = bus.publish("metrics", {"i": 1025})
    assert delivered == 0
