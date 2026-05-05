#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp>=1.0",
#     "httpx>=0.27",
# ]
# ///
"""KrakenOps MCP server (ADR 0007).

Stdio MCP server bundled in the krakenops-monitoring Claude Code plugin.
Exposes four tools the agent can call to bind itself to a GitHub Projects
v2 ticket, push status changes back, mirror its TODO list, and discover
which tickets are open.

The server is stateless — every tool call HTTP-POSTs to the local
KrakenOps backend. The backend resolves the calling Claude Code session
either from a ``session_id`` argument or, when omitted, by picking the
most-recently-active claude_code workstream (the single-session
heuristic; see ADR 0007 §"Session identity for MCP calls").

Configuration:
- ``KRAKENOPS_API`` env var overrides the default backend URL
  (``http://127.0.0.1:8787``).

Run via the plugin's ``mcpServers.krakenops`` entry —
``${CLAUDE_PLUGIN_ROOT}/server.py`` — or directly via
``uv run --script server.py`` for hand-testing the stdio JSON-RPC.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("KRAKENOPS_API", "http://127.0.0.1:8787").rstrip("/")
HTTP_TIMEOUT_S = 10.0

mcp = FastMCP("krakenops")


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Synchronous POST to the local backend. Errors surface as
    ``RuntimeError`` so the MCP framework returns them to the agent as
    tool errors (which Claude can read + react to)."""
    url = f"{API_BASE}{path}"
    try:
        resp = httpx.post(url, json=body, timeout=HTTP_TIMEOUT_S)
    except httpx.HTTPError as e:
        raise RuntimeError(f"krakenops backend unreachable at {url}: {e}") from e
    if resp.status_code >= 400:
        raise RuntimeError(
            f"krakenops backend {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def _get(path: str) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT_S)
    except httpx.HTTPError as e:
        raise RuntimeError(f"krakenops backend unreachable at {url}: {e}") from e
    if resp.status_code >= 400:
        raise RuntimeError(
            f"krakenops backend {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


# --- tools ---------------------------------------------------------------


@mcp.tool()
def claim_ticket(
    ticket_id: str,
    session_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Bind the calling Claude Code session to a GitHub Projects ticket.

    Once bound, the dashboard's workstream card shows the ticket title
    and the agent's live TODO progress against it. Status pushes via
    ``set_status`` then route through this binding.

    Args:
        ticket_id: GitHub ProjectV2Item node id (looks like
            ``PVTI_lAHOA…``). Use ``get_my_tickets`` to discover ids.
        session_id: Optional Claude Code session.id. When omitted the
            backend picks the most-recently-active claude_code session,
            which is correct for the common single-session case.
        project_id: Optional ``PVT_…`` project node id to record on the
            workstream. The backend infers it from the ticket if unset.

    Returns:
        ``{"bound": True, "bind_method": "mcp", "workstream_id": <int>}``
    """
    return _post(
        "/v1/workstreams/claim",
        {
            "ticket_id": ticket_id,
            "session_id": session_id,
            "project_id": project_id,
        },
    )


@mcp.tool()
def set_status(
    ticket_id: str,
    status: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Push a status change for a ticket back to GitHub Projects.

    ``status`` must match an option configured on the project's "Status"
    single-select field (e.g. "Todo", "In Progress", "Needs Human Review",
    "Done") — KrakenOps surfaces a 400 if the option doesn't exist.

    Args:
        ticket_id: GitHub ProjectV2Item node id.
        status: New status name. Whitespace and case must match the
            project's option.
        session_id: Optional — recorded informationally so the dashboard
            can attribute the change.

    Returns:
        ``{"ticket_id": ..., "status": ..., "agent_session_id": ...}``
    """
    return _post(
        f"/v1/tickets/{ticket_id}/status",
        {"status": status, "agent_session_id": session_id},
    )


@mcp.tool()
def set_todos(
    todos: list[dict[str, Any]],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Mirror the calling session's TODO checklist to KrakenOps.

    Equivalent to what the PostToolUse(TodoWrite) hook does
    automatically — provided here so non-Claude agents and explicit
    flows can populate the dashboard too.

    Args:
        todos: Replacement list. Each item: ``{content, activeForm?,
            status: "pending" | "in_progress" | "completed"}``.
        session_id: Optional Claude Code session.id.

    Returns:
        ``{"workstream_id": <int>, "todos_count": <int>}``
    """
    return _post(
        "/v1/workstreams/todos",
        {"todos": todos, "session_id": session_id},
    )


@mcp.tool()
def get_my_tickets(
    project_id: str | None = None,
    include_done: bool = False,
) -> dict[str, Any]:
    """List tickets the user has on KrakenOps-mirrored GitHub Projects.

    Useful for self-claim flows: ask the user "which one?", then call
    ``claim_ticket`` with the chosen ``id``.

    Args:
        project_id: Optional — filter to one project.
        include_done: Drop ``Done`` / closed tickets unless True.

    Returns:
        ``{"tickets": [{"id", "title", "status", "url", "project_id"}, ...]}``
    """
    body = _get("/v1/tickets")
    tickets = body.get("tickets") or []
    out: list[dict[str, Any]] = []
    terminal = {"Done", "Closed", "Canceled"}
    for t in tickets:
        if project_id and t.get("project_id") != project_id:
            continue
        if not include_done and t.get("status") in terminal:
            continue
        out.append(
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "status": t.get("status"),
                "url": t.get("url"),
                "project_id": t.get("project_id"),
            }
        )
    return {"tickets": out}


# --- entry point ---------------------------------------------------------


if __name__ == "__main__":
    # Stdio transport — Claude Code reads JSON-RPC frames over the
    # subprocess's stdin/stdout. FastMCP wraps the protocol details.
    mcp.run()
