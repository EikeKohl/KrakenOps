"""Workstream auto-discovery subscriber (ADR 0006).

Subscribes to the existing ``events`` pub/sub topic. For every Claude Code
log/metric record that carries a ``session.id`` we upsert a workstream
row keyed ``(source="claude_code", external_id=session.id)`` and republish
a fresh workstream snapshot on the ``workstreams`` topic so the dashboard
sees it within one round-trip.

The subscriber is owned by the FastAPI lifespan — same pattern as the
hardware sampler — so cancellation on shutdown is just ``task.cancel()``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.engine import Engine

from app.realtime import BUS
from app.workstreams.repo import (
    list_active_workstreams,
    upsert_external_workstream,
)

_log = logging.getLogger("krakenops.workstreams.subscriber")


def _attr_str(attrs: dict[str, Any], key: str) -> str | None:
    v = attrs.get(key)
    if isinstance(v, str):
        return v
    if v is None:
        return None
    return str(v)


def _label_for_session(session_id: str) -> str:
    """Compact human label — first 8 chars match what the dashboard shows."""
    short = session_id[:8] if session_id else "?"
    return f"Claude Code · sess {short}"


async def workstreams_loop(
    engine: Engine,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    """Drain the ``events`` queue forever, upserting workstreams.

    Each frame on the queue follows the bus envelope ``{topic, ts, data}``.
    We only react to Claude Code records that carry a ``session.id``;
    everything else slides past unchanged.
    """
    while True:
        msg = await queue.get()
        try:
            data = msg.get("data") or {}
            if data.get("service_name") != "claude-code":
                continue
            attrs = data.get("attributes") or {}
            session_id = (
                _attr_str(attrs, "session.id")
                or data.get("session_id")
            )
            if not session_id:
                continue
            ws_id = upsert_external_workstream(
                engine,
                source="claude_code",
                external_id=session_id,
                label=_label_for_session(session_id),
            )
            # Republish a fresh active-set snapshot so the dashboard sees the
            # new (or refreshed) workstream within one round-trip. Bounded —
            # downstream WS clients hit the same back-pressure rules as any
            # other publisher.
            BUS.publish(
                "workstreams",
                {"workstreams": list_active_workstreams(engine)},
            )
            _log.debug(
                "workstream upsert id=%s source=claude_code session=%s",
                ws_id, session_id,
            )
        except Exception:
            # Subscriber must never die — we'd lose all future workstreams.
            _log.exception("workstream subscriber failed on frame; continuing")


def start(engine: Engine) -> asyncio.Task[None]:
    """Spawn the auto-discovery subscriber as a background task."""
    queue = BUS.subscribe(["events"])
    return asyncio.create_task(
        workstreams_loop(engine, queue),
        name="krakenops-workstreams-subscriber",
    )
