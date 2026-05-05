"""Workstream model + auto-discovery (ADR 0006).

A *workstream* is "one running AI session the user cares about" — a Claude
Code CLI session, a tentacle-instrumented script, etc. Workstreams are
auto-discovered from the existing telemetry topics (`events`, `traces`)
and can be bound to a GitHub Projects ticket either via this package's
HTTP routes (manual claim from the dashboard) or — in Phase B (ADR 0007) —
the MCP server we ship in the Claude Code plugin.
"""

from app.workstreams.repo import (
    bind_workstream,
    end_workstream,
    find_by_external,
    list_active_workstreams,
    list_workstreams,
    unbind_workstream,
    update_todos,
    upsert_external_workstream,
)
from app.workstreams.subscriber import start as start_subscriber

__all__ = [
    "bind_workstream",
    "end_workstream",
    "find_by_external",
    "list_active_workstreams",
    "list_workstreams",
    "start_subscriber",
    "unbind_workstream",
    "update_todos",
    "upsert_external_workstream",
]
