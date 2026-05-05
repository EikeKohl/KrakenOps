"""KrakenOps backend entry point.

Lifespan runs migrations + seeds model_pricing + starts the psutil sampler
+ starts the GitHub poller (when configured). See ../../CLAUDE.md §5 and
ADR 0002.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config_file import load as load_file_config
from app.db.session import init_db
from app.poller import start as start_poller
from app.realtime import ws as realtime_ws
from app.routes import (
    agents,
    costs,
    events,
    health,
    logs_ingest,
    metrics_ingest,
    processes,
    projects,
    spans,
    tickets,
    traces,
    workstreams,
)
from app.sampler import loop as sampler_loop_module
from app.sampler import processes as processes_sampler
from app.workstreams import start_subscriber

_log = logging.getLogger("krakenops.backend")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _self_endpoint() -> str:
    """Endpoint the orchestrator passes to spawned agents (for OTel export)."""
    port = os.environ.get("KRAKENOPS_PORT", "8787")
    return f"http://127.0.0.1:{port}/v1/traces"


@asynccontextmanager
async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
    init_db()
    sampler_task = sampler_loop_module.start(interval_s=1.0)

    file_config = load_file_config()
    from app.db import engine

    processes_task = processes_sampler.start(
        engine,
        file_config.processes.allowlist,
        interval_s=1.0,
        denylist=file_config.processes.denylist,
    )

    poller_tasks, github_clients = start_poller(engine, file_config, _self_endpoint())

    # ADR 0006: workstreams auto-discovery subscriber on the events topic.
    workstreams_task = start_subscriber(engine)

    # Route handlers reach the GitHub clients + agent mappings via app.state.
    # `github_clients` is a list (one per project, ADR 0006); the manual
    # spawn route uses the first one for now.
    app_.state.github_clients = github_clients
    app_.state.github_client = github_clients[0] if github_clients else None
    app_.state.agents = file_config.agents
    app_.state.backend_endpoint = _self_endpoint()

    _log.info(
        "krakenops backend ready (poller=%s projects, agents=%d, processes=%s)",
        len(poller_tasks),
        len(file_config.agents),
        "on" if file_config.processes.enabled else "off",
    )
    try:
        yield
    finally:
        background_tasks: list[asyncio.Task[None] | None] = list(poller_tasks)
        background_tasks.extend([sampler_task, processes_task, workstreams_task])
        for task in background_tasks:
            if task is None:
                continue
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task


app = FastAPI(
    title="KrakenOps Backend",
    version=__version__,
    description="Local-first ingest + orchestration for KrakenOps.",
    lifespan=lifespan,
)

# Local-first: dashboard runs on the same host but a different port (3000 by
# default, 3001 if 3000 is taken). Allow it to call the REST API from the
# browser. Override via KRAKENOPS_CORS_ORIGINS (comma-separated) when needed.
_default_origins = (
    "http://localhost:3000,http://localhost:3001,"
    "http://127.0.0.1:3000,http://127.0.0.1:3001"
)
_cors_origins = [
    o.strip()
    for o in os.environ.get("KRAKENOPS_CORS_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(traces.router)
app.include_router(spans.router)
app.include_router(costs.router)
app.include_router(tickets.router)
app.include_router(agents.router)
app.include_router(metrics_ingest.router)
app.include_router(logs_ingest.router)
app.include_router(processes.router)
app.include_router(events.router)
app.include_router(projects.router)
app.include_router(workstreams.router)
app.include_router(realtime_ws.router)
