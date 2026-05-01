"""GitHub Projects v2 poller + agent subprocess orchestration. See ADR 0002."""

from app.poller.github import FakeGitHubClient, GitHubClient, GitHubGraphQLClient, TicketItem
from app.poller.loop import start, tick
from app.poller.orchestrator import run_agent

__all__ = [
    "FakeGitHubClient",
    "GitHubClient",
    "GitHubGraphQLClient",
    "TicketItem",
    "run_agent",
    "start",
    "tick",
]
