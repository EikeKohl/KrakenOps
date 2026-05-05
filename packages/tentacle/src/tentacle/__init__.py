"""Tentacle — agent-agnostic OpenTelemetry decorators for KrakenOps.

Public API:

    import tentacle

    tentacle.init(endpoint="http://localhost:8787/v1/traces")

    @tentacle.track_agent
    def research(topic: str) -> str: ...

    @tentacle.tool
    def gather(topic: str) -> list[str]: ...

    @tentacle.require_human
    def confirm(choice: str) -> bool:
        if ambiguous(choice):
            raise tentacle.NeedsHumanReview("pick one", payload={"options": [...]})
        ...

    # ADR 0008 — workstream + ticket plumbing for the KrakenOps dashboard:
    tentacle.register_workstream(label="my-agent")
    tentacle.claim_ticket("PVTI_…")
    tentacle.set_todos([{"content": "do x", "status": "pending"}])
    tentacle.set_status("PVTI_…", "Needs Human Review")

See ADR 0001 for the span schema, ADR 0008 for the status / TODO surface.
"""

from __future__ import annotations

from tentacle._core import init
from tentacle._decorators import require_human, tool, track_agent
from tentacle._exceptions import NeedsHumanReview
from tentacle._status import claim_ticket, register_workstream, set_status, set_todos
from tentacle._version import __version__

__all__ = [
    "NeedsHumanReview",
    "__version__",
    "claim_ticket",
    "init",
    "register_workstream",
    "require_human",
    "set_status",
    "set_todos",
    "tool",
    "track_agent",
]
