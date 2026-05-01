#!/usr/bin/env bash
#
# e2e.sh — end-to-end smoke test.
#
# Boots the backend against a temp DB, runs the example agent, asserts the
# trace landed via /v1/traces, and asserts that the metrics WebSocket topic
# is broadcasting. GitHub orchestration in PR #7.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${KRAKENOPS_PORT:-8788}"   # different default from /dev-up to avoid collision
TMPHOME="$(mktemp -d -t krakenops-e2e-XXXXXX)"
export KRAKENOPS_HOME="$TMPHOME"
export KRAKENOPS_DB_PATH="$TMPHOME/krakenops.db"

PIDS=()
cleanup() {
    rc=$?
    for pid in "${PIDS[@]:-}"; do
        # Kill the subshell AND any uvicorn it spawned via `uv run`.
        pkill -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
    done
    # Belt-and-braces: anything still listening on our port is ours.
    if lsof -i ":$PORT" -sTCP:LISTEN -t 2>/dev/null | xargs -r kill 2>/dev/null; then :; fi
    rm -rf "$TMPHOME"
    exit "$rc"
}
trap cleanup EXIT INT TERM

echo "→ tmp home: $TMPHOME"

if lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✗ port $PORT already in use — aborting (e2e refuses to talk to a stale backend)"
    lsof -i ":$PORT" -sTCP:LISTEN
    exit 1
fi

echo "→ starting backend on :$PORT"
( cd apps/backend && uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    >/tmp/krakenops-e2e-backend.log 2>&1 ) &
PIDS+=($!)

# Wait up to 15s for /v1/health.
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/v1/health" | grep -q '"ok":true' || {
    echo "✗ backend never came up — log:"; tail /tmp/krakenops-e2e-backend.log; exit 1
}
echo "✓ backend healthy"

# Run the example agent against this backend.
echo "→ running examples/hello_agent.py"
( cd packages/tentacle && uv run python ../../examples/hello_agent.py \
    --count 3 --endpoint "http://127.0.0.1:$PORT/v1/traces" >/tmp/krakenops-e2e-agent.log 2>&1 )
echo "✓ agent ran"

# BatchSpanProcessor flushes on Python exit; give the export a beat.
sleep 1

# Assert: at least one trace landed via REST.
COUNT=$(curl -fsS "http://127.0.0.1:$PORT/v1/traces?limit=50" \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["traces"]))')
echo "→ traces reported by /v1/traces: $COUNT"
if [ "$COUNT" -lt 1 ]; then
    echo "✗ no traces ingested — agent log:"; cat /tmp/krakenops-e2e-agent.log; exit 1
fi
echo "✓ /v1/traces shows ingested data"

# Assert: WS metrics topic is broadcasting.
echo "→ subscribing to ws://127.0.0.1:$PORT/v1/ws?topics=metrics"
( cd apps/backend && uv run python ../../scripts/_ws_smoke.py \
    --url "ws://127.0.0.1:$PORT/v1/ws" --topics metrics --timeout 5 )
echo "✓ ws metrics topic broadcasting"

# TODO(PR #7): run a synthetic GH ticket through the orchestration loop.

echo "✓ e2e smoke (PR #5 scope) passed"
