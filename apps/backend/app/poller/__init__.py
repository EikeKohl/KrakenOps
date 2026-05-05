"""GitHub Projects v2 poller. See ADR 0002 + ADR 0006.

Multi-project mirror: one async tick task per project. The orchestrator
remains importable for the manual ``/v1/tickets/{id}/spawn`` endpoint, but
the auto-spawn-on-Todo path was removed in ADR 0006 — KrakenOps is now
read-only; agents claim tickets via MCP or the dashboard, not by being
spawned.
"""

from app.poller.github import (
    FakeGitHubClient,
    GitHubClient,
    GitHubGraphQLClient,
    ProjectSnapshot,
    TicketItem,
)
from app.poller.loop import start, tick
from app.poller.orchestrator import run_agent

__all__ = [
    "FakeGitHubClient",
    "GitHubClient",
    "GitHubGraphQLClient",
    "ProjectSnapshot",
    "TicketItem",
    "run_agent",
    "start",
    "tick",
]
