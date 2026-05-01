"""psutil sampler: snapshot shape + loop publishes via injected callback."""

from __future__ import annotations

import asyncio
import contextlib

from app.sampler.loop import sampler_loop, take_snapshot


def test_snapshot_shape() -> None:
    snap = take_snapshot()
    assert set(snap.keys()) == {"cpu_pct", "ram_pct", "disk_pct", "ts_ns"}
    assert 0.0 <= snap["cpu_pct"] <= 100.0
    assert 0.0 <= snap["ram_pct"] <= 100.0
    assert 0.0 <= snap["disk_pct"] <= 100.0
    assert isinstance(snap["ts_ns"], int)


async def test_loop_publishes_on_each_tick() -> None:
    received: list[tuple[str, dict]] = []

    def fake_publish(topic: str, data: dict) -> int:
        received.append((topic, data))
        return 1

    task = asyncio.create_task(
        sampler_loop(interval_s=0.05, publish=fake_publish)
    )
    # Let it tick a few times.
    await asyncio.sleep(0.18)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # 0.18 / 0.05 ≈ 3 ticks (timing slack acceptable).
    assert len(received) >= 2
    assert all(topic == "metrics" for topic, _ in received)
    expected_keys = {"cpu_pct", "ram_pct", "disk_pct", "ts_ns"}
    assert all(set(data.keys()) == expected_keys for _, data in received)
