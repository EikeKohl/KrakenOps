"""Exceptions raised by user code that the SDK observes."""

from __future__ import annotations

from typing import Any


class NeedsHumanReview(Exception):  # noqa: N818  # public API name; see ADR 0001
    """Raised by user code to pause an agent and request human input.

    The KrakenOps backend recognizes this exception's span signature and
    transitions the corresponding GitHub Project ticket to "Needs Human Review".
    See ADR 0001 for the wire-format contract.
    """

    def __init__(self, prompt: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(prompt)
        self.prompt = prompt
        self.payload = payload or {}
