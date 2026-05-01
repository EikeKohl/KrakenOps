"""WebSocket endpoint.

A single endpoint at GET /v1/ws multiplexes all topics. Clients pass a
comma-separated list via the `?topics=` query string; default is all known
topics. The protocol is broadcast-only (server → client). The server drains
client-sent frames purely to detect disconnect.

Wire envelope (per CLAUDE.md §2.1 / dashboard's lib/ws.ts):

    { "topic": "metrics", "ts": <ns>, "data": { ... } }
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from app.realtime.bus import BUS, TOPICS

_log = logging.getLogger("krakenops.realtime.ws")

router = APIRouter()


@router.websocket("/v1/ws")
async def ws_endpoint(ws: WebSocket, topics: str = ",".join(TOPICS)) -> None:
    requested = [t.strip() for t in topics.split(",") if t.strip()]
    valid = [t for t in requested if t in TOPICS]
    await ws.accept()
    if not valid:
        await ws.close(code=1003, reason=f"no valid topics; allowed: {TOPICS}")
        return
    queue = BUS.subscribe(valid)
    _log.info("ws client subscribed to %s", valid)

    sender = asyncio.create_task(_sender(ws, queue), name="ws-sender")
    receiver = asyncio.create_task(_receiver(ws), name="ws-receiver")

    try:
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        # Surface non-disconnect errors to the log.
        for task in done:
            try:
                task.result()
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            except Exception:
                _log.exception("ws task error")
    finally:
        BUS.unsubscribe(queue, valid)
        if ws.client_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await ws.close()
        _log.info("ws client disconnected from %s", valid)


async def _sender(ws: WebSocket, queue: asyncio.Queue[dict]) -> None:
    while True:
        msg = await queue.get()
        await ws.send_json(msg)


async def _receiver(ws: WebSocket) -> None:
    # We don't expect inbound frames, but receiving lets us detect disconnect.
    while True:
        await ws.receive_text()
