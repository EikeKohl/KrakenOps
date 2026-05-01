"""Hardware sampler.

A single asyncio task drives `psutil` at 1 Hz and publishes a snapshot on the
`metrics` topic. `psutil.cpu_percent(interval=None)` is non-blocking — its
first call returns 0.0, subsequent calls return delta-since-last-call. Disk
percent is the root volume.

The task is started by the FastAPI lifespan and cancelled on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import psutil

from app.realtime import BUS

_log = logging.getLogger("krakenops.sampler")


def take_snapshot(disk_path: str = "/") -> dict[str, Any]:
    """Pure measurement helper. Easily called from tests."""
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_pct": psutil.virtual_memory().percent,
        "disk_pct": psutil.disk_usage(disk_path).percent,
        "ts_ns": time.time_ns(),
    }


async def sampler_loop(
    interval_s: float = 1.0,
    disk_path: str = "/",
    publish: Callable[[str, Any], int] = BUS.publish,
) -> None:
    """Run forever (until cancelled), publishing a metrics snapshot every `interval_s`."""
    # First call primes the CPU delta — discard its 0.0 reading without sleeping.
    psutil.cpu_percent(interval=None)
    _log.info("sampler started @ %.2fs interval", interval_s)
    try:
        while True:
            snap = take_snapshot(disk_path=disk_path)
            publish("metrics", snap)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        _log.info("sampler stopped")
        raise


def start(interval_s: float = 1.0) -> asyncio.Task[None]:
    """Spawn the sampler as a background task on the current event loop."""
    return asyncio.create_task(sampler_loop(interval_s=interval_s), name="krakenops-sampler")
