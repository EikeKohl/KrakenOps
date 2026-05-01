#!/usr/bin/env bash
#
# dev-up.sh — start the full KrakenOps stack locally.
#
# Boots:
#   • backend   uv run uvicorn app.main:app --port 8787 --reload     (apps/backend)
#   • dashboard pnpm dev                                              (apps/dashboard, port 3000)
#
# Logs are interleaved with [backend] / [dashboard] prefixes. Ctrl+C tears
# both down.
#
# Prereqs:  uv, pnpm, Python ≥3.10, Node ≥20.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- preflight -----------------------------------------------------------
command -v uv   >/dev/null || { echo "✗ uv not installed: https://github.com/astral-sh/cargo-dist"; exit 1; }
command -v pnpm >/dev/null || { echo "✗ pnpm not installed: https://pnpm.io/installation";        exit 1; }

if lsof -i :8787 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✗ port 8787 is in use — free it before starting the backend."
    exit 1
fi
if lsof -i :3000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✗ port 3000 is in use — free it before starting the dashboard."
    exit 1
fi

# --- ensure deps ---------------------------------------------------------
if [ ! -d apps/backend/.venv ];        then ( cd apps/backend   && uv sync ); fi
if [ ! -d apps/dashboard/node_modules ];then ( cd apps/dashboard && pnpm install ); fi

# --- launch --------------------------------------------------------------
pids=()
trap 'echo; echo "↓ shutting down…"; kill "${pids[@]}" 2>/dev/null || true; wait || true' INT TERM EXIT

(
    cd apps/backend
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload 2>&1 \
        | sed -u 's/^/[backend]   /'
) &
pids+=($!)

(
    cd apps/dashboard
    pnpm dev 2>&1 | sed -u 's/^/[dashboard] /'
) &
pids+=($!)

echo "↑ stack starting — backend :8787 · dashboard :3000 · ctrl+c to stop"
wait
