# krakenops-monitoring (Claude Code plugin)

Adds KrakenOps integration to Claude Code:

- **Live TODO list on the dashboard.** A `PostToolUse(TodoWrite)` hook
  POSTs the new checklist to the local backend after every `TodoWrite`
  call; the workstream card updates within ~1 s.
- **Self-claim and status push-back via MCP.** Four tools the agent can
  call:
  - `krakenops.claim_ticket(ticket_id, session_id?, project_id?)`
  - `krakenops.set_status(ticket_id, status, session_id?)`
  - `krakenops.set_todos(todos, session_id?)`
  - `krakenops.get_my_tickets(project_id?, include_done?)`
- **Session lifecycle markers.** `SessionStart` / `SessionEnd` hooks
  keep the workstream's `started_at_s` / `ended_at_s` honest.

Without this plugin KrakenOps still sees Claude Code sessions
(auto-discovered from OpenTelemetry — see ADR 0006), but TODOs and
agent-driven binding don't fire.

## Install

```sh
claude --plugin-dir ./packages/krakenops-claude-plugin
```

That loads the plugin for the current `claude` invocation. To install
permanently, follow the regular plugin marketplace flow (see the
[Claude Code plugins docs](https://code.claude.com/docs/en/plugins.md)).

The wizard at `scripts/setup.sh` offers to wire this up for you.

## Requirements

- `uv` on `PATH` — the MCP server is a single `server.py` with PEP 723
  inline deps; uv resolves `mcp` + `httpx` on first run.
- A running KrakenOps backend on `http://127.0.0.1:8787` (override with
  `KRAKENOPS_API`). The hooks degrade silently if it's down — Claude
  Code logs the timeout but doesn't block tool execution.

## Layout

```
packages/krakenops-claude-plugin/
├── .claude-plugin/
│   └── plugin.json     # manifest + mcpServers
├── hooks/
│   └── hooks.json      # PostToolUse(TodoWrite), SessionStart, SessionEnd
├── server.py           # stdio MCP server (uv run --script)
└── README.md
```

## How it talks to KrakenOps

| Surface | What it calls |
| --- | --- |
| `PostToolUse(TodoWrite)` hook | `POST /v1/hooks/claude/post-tool-use` |
| `SessionStart` hook            | `POST /v1/hooks/claude/session-start` |
| `SessionEnd` hook              | `POST /v1/hooks/claude/session-end`   |
| MCP `claim_ticket`             | `POST /v1/workstreams/claim`          |
| MCP `set_status`               | `POST /v1/tickets/{id}/status`        |
| MCP `set_todos`                | `POST /v1/workstreams/todos`          |
| MCP `get_my_tickets`           | `GET /v1/tickets` (filtered locally)  |

All endpoints are documented in
[ADR 0007](../../docs/adr/0007-claude-code-plugin-and-mcp.md).

## Session-id resolution

Claude Code does not pass a session env var to MCP servers. Each tool
accepts an optional `session_id` parameter; when omitted the backend
binds to "the most-recently-active claude_code workstream", which is
correct for the typical single-session case. Pass `session_id`
explicitly when running multiple Claude Code sessions concurrently.

## Local testing

You can hand-test the MCP server outside Claude Code:

```sh
KRAKENOPS_API=http://127.0.0.1:8787 uv run --script packages/krakenops-claude-plugin/server.py
```

It speaks JSON-RPC on stdin/stdout. Send an `initialize` frame, then
`tools/list` to see all four tools and `tools/call` to invoke one.
