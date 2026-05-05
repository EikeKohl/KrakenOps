"""hello_agent.py — minimal example exercising the tentacle decorators.

Used by the `/seed-traces` skill and `scripts/e2e.sh`. Demonstrates:

- ``@tentacle.track_agent`` / ``@tentacle.tool`` / ``NeedsHumanReview``
  (the original v0.1 surface — ADR 0001).
- ``tentacle.register_workstream`` / ``set_todos`` / (optionally)
  ``claim_ticket`` and ``set_status`` (ADR 0008). The script will show
  up as a workstream card on the dashboard, with the TODO list updating
  as it works through the run.

Usage:
    python examples/hello_agent.py --count 5 --endpoint http://localhost:8787/v1/traces
    python examples/hello_agent.py --ticket-id PVTI_lAHO…  # also claims the ticket
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
    parser.add_argument(
        "--ticket-id",
        default=os.environ.get("KRAKENOPS_TICKET_ID"),
        help="GitHub Projects v2 item id (PVTI_…) — when set, the script "
        "claims this ticket and flips its status to 'Needs Human Review' "
        "on completion.",
    )
    args = parser.parse_args()

    tentacle.init(endpoint=args.endpoint)

    # ADR 0008: surface this run as a workstream on the dashboard.
    session_id = tentacle.register_workstream(
        label=f"hello_agent (n={args.count})",
    )
    print(f"workstream session: {session_id}")

    if args.ticket_id:
        tentacle.claim_ticket(args.ticket_id)
        print(f"claimed ticket {args.ticket_id}")

    todos = [
        {"content": f"Research topic {i + 1}", "activeForm": f"Researching topic {i + 1}",
         "status": "pending"}
        for i in range(args.count)
    ]
    tentacle.set_todos(todos)

    topics = ["mac mini", "open source", "fastapi", "next.js", "opentelemetry"]
    for i in range(args.count):
        topic = random.choice(topics)
        # Mark the current item in_progress; everything below it stays pending.
        for j, item in enumerate(todos):
            if j < i:
                item["status"] = "completed"
            elif j == i:
                item["status"] = "in_progress"
            else:
                item["status"] = "pending"
        tentacle.set_todos(todos)

        try:
            print(f"[{i + 1}/{args.count}] research({topic!r}) → {research(topic)}")
        except tentacle.NeedsHumanReview as e:
            print(f"[{i + 1}/{args.count}] research({topic!r}) → paused: {e.prompt}")
            if args.ticket_id:
                tentacle.set_status(args.ticket_id, "Needs Human Review")
            return 0
        time.sleep(0.05)

    # All TODOs done.
    for item in todos:
        item["status"] = "completed"
    tentacle.set_todos(todos)

    if args.ticket_id:
        tentacle.set_status(args.ticket_id, "Done")
        print(f"ticket {args.ticket_id} → Done")

    return 0


if __name__ == "__main__":
    sys.exit(main())
