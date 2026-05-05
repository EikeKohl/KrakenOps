#!/usr/bin/env bash
#
# install-claude-code-telemetry.sh — one-time setup for ADR 0005.
#
# Appends the five env vars Claude Code reads at startup to your shell rc so
# the local KrakenOps backend starts receiving its OTel metrics + logs:
#
#     CLAUDE_CODE_ENABLE_TELEMETRY=1
#     OTEL_METRICS_EXPORTER=otlp
#     OTEL_LOGS_EXPORTER=otlp
#     OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
#     OTEL_EXPORTER_OTLP_ENDPOINT=$KRAKENOPS_ENDPOINT (default http://localhost:8787)
#
# Idempotent — re-running is a no-op.
# Reversible — `install-claude-code-telemetry.sh uninstall` removes the block.
#
# Why this works for both the Claude Code CLI and the VS Code extension:
# the CLI reads the shell env directly; VS Code on macOS resolves the user's
# login-shell environment once at startup and propagates it to extension
# subprocesses (this is its "automatic shell environment" feature). So a
# single rc-file edit covers both surfaces.
#
set -euo pipefail

ENDPOINT="${KRAKENOPS_ENDPOINT:-http://localhost:8787}"

# Pick the shell rc — zsh is the macOS default; fall back to bash if the
# user is on bash and has no .zshrc.
RC="${HOME}/.zshrc"
if [[ ! -f "$RC" && -f "${HOME}/.bashrc" ]]; then
    RC="${HOME}/.bashrc"
fi

START_MARK="# >>> krakenops claude-code telemetry >>>"
END_MARK="# <<< krakenops claude-code telemetry <<<"

emit_block() {
    cat <<EOF

$START_MARK
# Installed by scripts/install-claude-code-telemetry.sh — see ADR 0005.
# Remove with: scripts/install-claude-code-telemetry.sh uninstall
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=$ENDPOINT
$END_MARK
EOF
}

cmd="${1:-install}"

case "$cmd" in
    install)
        if grep -qF "$START_MARK" "$RC" 2>/dev/null; then
            echo "✓ already installed in $RC (no-op)"
            exit 0
        fi
        emit_block >> "$RC"
        echo "✓ wrote Claude Code telemetry env vars to $RC"
        echo
        echo "Next steps:"
        echo "  1. New terminals pick this up automatically."
        echo "     For the current shell:    source \"$RC\""
        echo "  2. Quit VS Code fully (Cmd+Q) and relaunch — it captures the"
        echo "     login-shell env once at startup."
        echo "  3. Verify:    env | grep -E 'CLAUDE_CODE|OTEL_'"
        echo
        echo "Backend endpoint: $ENDPOINT"
        echo "(Override with KRAKENOPS_ENDPOINT=... before running this script.)"
        ;;
    uninstall)
        if ! grep -qF "$START_MARK" "$RC" 2>/dev/null; then
            echo "✓ not installed in $RC (no-op)"
            exit 0
        fi
        # Portable in-place edit: BSD sed and GNU sed disagree on -i, so
        # round-trip via a temp file.
        awk -v start="$START_MARK" -v end="$END_MARK" '
            $0 == start { skip = 1; next }
            $0 == end   { skip = 0; next }
            !skip       { print }
        ' "$RC" > "$RC.krakenops.tmp" && mv "$RC.krakenops.tmp" "$RC"
        echo "✓ removed Claude Code telemetry block from $RC"
        echo "  Quit + relaunch your terminal (and VS Code) to drop the vars."
        ;;
    *)
        echo "Usage: $0 [install|uninstall]" >&2
        exit 2
        ;;
esac
