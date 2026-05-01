"""hello_agent.py — minimal example exercising the tentacle decorators.

Used by the `/seed-traces` skill and `scripts/e2e.sh`. In v0.0.0 the decorators
are no-ops, so this just runs locally and prints output. Once `tentacle` v0.1
ships (PR #3), the same script will export OTel spans to the configured endpoint.

Usage:
    python examples/hello_agent.py --count 5 --endpoint http://localhost:8787/v1/traces
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time

import tentacle


@tentacle.tool
def gather_notes(topic: str) -> list[str]:
    return [f"note about {topic} #{i}" for i in range(random.randint(2, 4))]


@tentacle.tool
def summarize(notes: list[str]) -> str:
    if random.random() < 0.1:
        raise tentacle.NeedsHumanReview(
            prompt="Sources disagree — which one should I trust?",
            payload={"options": notes[:2]},
        )
    return f"Summary of {len(notes)} notes."


@tentacle.track_agent
def research(topic: str) -> str:
    notes = gather_notes(topic)
    return summarize(notes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("TENTACLE_ENDPOINT", "http://localhost:8787/v1/traces"),
    )
    args = parser.parse_args()

    tentacle.init(endpoint=args.endpoint)

    topics = ["mac mini", "open source", "fastapi", "next.js", "opentelemetry"]
    for i in range(args.count):
        topic = random.choice(topics)
        try:
            print(f"[{i + 1}/{args.count}] research({topic!r}) → {research(topic)}")
        except tentacle.NeedsHumanReview as e:
            print(f"[{i + 1}/{args.count}] research({topic!r}) → paused: {e.prompt}")
        time.sleep(0.05)
    return 0


if __name__ == "__main__":
    sys.exit(main())
