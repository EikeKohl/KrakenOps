#!/usr/bin/env bash
#
# setup.sh — interactive KrakenOps install wizard.
#
# Walks you through:
#   1. ~/.krakenops/config.toml (GitHub PAT + project, process allowlist)
#   2. Claude Code telemetry env block in your shell rc
#   3. Backend connectivity probe
#
# Standalone — needs only python3 (any 3.10+). Re-run anytime; idempotent.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "✗ python3 not found on PATH — install it first." >&2
    exit 1
fi

exec python3 "$ROOT/scripts/krakenops_setup.py" "$@"
