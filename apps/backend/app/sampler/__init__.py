"""psutil samplers (1 Hz).

- ``loop``      — host hardware → ``metrics`` pub/sub topic.
- ``processes`` — per-process discovery → ``processes`` pub/sub topic (ADR 0005).
"""

from app.sampler.loop import sampler_loop, start, take_snapshot

__all__ = ["sampler_loop", "start", "take_snapshot"]
