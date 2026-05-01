"""Tiny WS subscriber used by scripts/e2e.sh.

Subscribes to one or more topics on /v1/ws and waits for the first message,
or times out. Exits 0 on receipt, 1 on timeout / error.

Usage:
    python scripts/_ws_smoke.py --url ws://127.0.0.1:8788/v1/ws \\
        --topics metrics --timeout 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from websockets.asyncio.client import connect


async def _wait_one(url: str, topics: str, timeout: float) -> int:
    qs = f"?topics={topics}"
    try:
        async with connect(url + qs) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            print(f"✓ ws received topic={msg.get('topic')!r} ts={msg.get('ts')}")
            return 0
    except TimeoutError:
        print(f"✗ ws timed out after {timeout}s waiting for topics={topics}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"✗ ws error: {e}", file=sys.stderr)
        return 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--topics", default="metrics")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()
    return asyncio.run(_wait_one(args.url, args.topics, args.timeout))


if __name__ == "__main__":
    sys.exit(main())
