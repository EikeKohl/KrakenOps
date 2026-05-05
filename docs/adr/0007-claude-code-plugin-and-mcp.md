# ADR 0007: KrakenOps Claude Code plugin (hooks + MCP)

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @eikekohlmeyer
- **Affects:** backend · plugin · contract

## Context

ADR 0006 wired up workstreams that auto-discover Claude Code sessions from
the OTel `events` topic. That gets us *visibility* with zero install:
sessions show up as cards within ~2 s. But the v1 vision needs three more
things that OTel alone can't deliver:

1. **The TODO list.** Claude Code's `TodoWrite` tool maintains a live
   per-session checklist. It is **not** exported via OTel — only visible
   in the CLI UI ([Claude Code docs § monitoring](https://code.claude.com/docs/en/monitoring-usage)
   confirm this; ADR 0006's exploration phase double-checked it).
2. **Self-claim by the agent.** When the user prompts "work on issue #42",
   the agent should be able to bind its workstream to that ticket without
   the user dropping into the dashboard.
3. **Status push-back.** When the agent is done, it should be able to
   flip the ticket from `In Progress` → `Needs Human Review` → `Done`
   without the user having to PATCH GitHub by hand.

Two channels Claude Code already exposes solve all three:

- **Hooks** — `PostToolUse`, `SessionStart`, `SessionEnd` — can POST JSON
  to a local HTTP endpoint when fired ([hooks docs](https://code.claude.com/docs/en/hooks.md)).
- **MCP servers** — Claude Code consumes MCP tools registered via a
  plugin's `mcpServers` block ([mcp docs](https://code.claude.com/docs/en/mcp.md)).

The plugin packages both behind a `claude --plugin-dir ./packages/krakenops-claude-plugin`
install — one command, no per-session config.

## Decision

### Plugin layout

Per the Claude Code plugin spec ([plugins-reference](https://code.claude.com/docs/en/plugins-reference.md)):

```
packages/krakenops-claude-plugin/
├── .claude-plugin/
│   └── plugin.json          # manifest (name, version, description, mcpServers)
├── hooks/
│   └── hooks.json           # PostToolUse(TodoWrite), SessionStart, SessionEnd
├── server.py                # MCP stdio server, PEP 723 inline deps
└── README.md
```

`mcpServers` is **inlined into `plugin.json`** rather than living in a
separate `.mcp.json` — keeps the plugin a single artifact.

### Hooks

Three hooks, all HTTP-typed, all firing against the local backend
(`http://127.0.0.1:8787`):

| Event | Matcher | Endpoint                                |
| ----- | ------- | --------------------------------------- |
| `PostToolUse` | `TodoWrite` | `POST /v1/hooks/claude/post-tool-use` |
| `SessionStart` | (any) | `POST /v1/hooks/claude/session-start` |
| `SessionEnd`   | (any) | `POST /v1/hooks/claude/session-end`   |

Hook input JSON (confirmed against the docs) carries:
`session_id`, `tool_name`, `tool_input`, `tool_use_id`, `cwd`,
`permission_mode`, `transcript_path`, `hook_event_name`.

For `PostToolUse(TodoWrite)`, `tool_input.todos` is the **whole new TODO
list** — `TodoWrite` replaces, doesn't append — so the backend only ever
needs to store the latest payload. Each item carries
`{content, activeForm, status}`.

### MCP server

Stdio transport. Single file, PEP 723 inline deps so the user gets
`mcp + httpx` automatically via `uv run --script` — no manual install.

```jsonc
// .claude-plugin/plugin.json (excerpt)
{
  "mcpServers": {
    "krakenops": {
      "command": "uv",
      "args": ["run", "--script", "${CLAUDE_PLUGIN_ROOT}/server.py"]
    }
  }
}
```

Tools the server exposes (all under the `krakenops.*` namespace):

| Tool                               | Body                              | Backend call                                       |
| ---------------------------------- | --------------------------------- | -------------------------------------------------- |
| `krakenops.claim_ticket`           | `ticket_id`, optional `session_id`, optional `project_id` | `POST /v1/workstreams/{ws_id}/bind`                |
| `krakenops.set_status`             | `ticket_id`, `status`             | `POST /v1/tickets/{ticket_id}/status`              |
| `krakenops.set_todos`              | `todos`, optional `session_id`    | `POST /v1/hooks/claude/post-tool-use` (hook shape) |
| `krakenops.get_my_tickets`         | optional `project_id`             | `GET /v1/tickets`, server-side filter              |

### Session identity for MCP calls

Claude Code does **not** pass a `CLAUDE_SESSION_ID` env var to MCP servers
([per the docs](https://code.claude.com/docs/en/mcp.md), MCP servers run as
fresh subprocesses per Claude Code session but receive no built-in identity).
Resolution strategy in v1:

1. **Tool-arg passthrough** — every workstream-scoped tool accepts an
   optional `session_id` parameter. The agent can read its own
   `session.id` from a `SessionStart` hook (`/v1/hooks/claude/session-start`
   echoes the `session_id` back into the workstream's label) and pass it
   through.
2. **Heuristic fallback** — when `session_id` is omitted, the backend
   resolves "the most-recently-active `claude_code` workstream that's
   either unbound or whose binding is `auto` / `manual`". Single-session
   usage (the common case) Just Works.
3. **No multi-session disambiguation in v1.** If two Claude Code sessions
   call `claim_ticket()` concurrently without `session_id`, behavior is
   ambiguous (the most-recent wins). Documented as a known limitation;
   the MCP tool description nudges agents to pass `session_id`.

### Backend additions

`apps/backend/app/routes/hooks.py` (new):

- `POST /v1/hooks/claude/post-tool-use` — parses Claude Code's hook
  payload. If `tool_name == "TodoWrite"`, persists `tool_input.todos`
  to the matching workstream's `todos_json` (and creates the workstream
  if it hasn't been seen yet — covers the case where the plugin is
  installed before any OTel event lands).
- `POST /v1/hooks/claude/session-start` — upserts the workstream and
  echoes back `{workstream_id, session_id}` in case the agent wants to
  log it.
- `POST /v1/hooks/claude/session-end` — sets `ended_at_s`.

`apps/backend/app/routes/tickets.py` (extension):

- `POST /v1/tickets/{ticket_id}/status` body `{status, agent_session_id?}`.
  Pushes via the existing per-project `GitHubGraphQLClient.set_status`,
  optimistically updates the local row, returns the new status.

No schema migration needed — Phase B reuses Phase A's `workstreams.todos_json`
column.

## Consequences

### Positive
- Live TODO progress on every workstream card without changing the user's
  Claude Code workflow.
- Bind by the agent ("work on issue #42" → MCP → backend → bound) feels
  invisible.
- Status push-back closes the loop: agent finishes → ticket moves on
  GitHub → poller picks it up → kanban panel updates.
- Single artifact (`packages/krakenops-claude-plugin/`) installs via one
  CLI command. No global Python deps thanks to PEP 723.

### Negative / accepted risks
- The plugin runs only when the user installs it. Visibility (workstreams
  appearing on the dashboard) still works without it because Phase A's
  auto-discovery rides on OTel — but TODOs and MCP-driven bind do not.
  Documented in the plugin's README.
- The session-id resolution heuristic is explicit. Multi-session safety
  ships as a follow-up (most likely a per-process registration token the
  MCP server prints on startup that the agent can read from stderr/log).
- `POST /v1/hooks/claude/post-tool-use` ingests untrusted JSON. Bound by
  payload size (default 1 MB) and the schema we explicitly read; we
  silently drop unknown shapes rather than throwing 500s. Local-first
  posture (CLAUDE.md §1) means we don't auth this endpoint.
- The MCP server depends on `uv` being on the user's PATH. The wizard
  already requires uv for the backend, so this isn't a new requirement,
  but worth flagging in the plugin README.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR; new `tests/contract/claude_hook_post_tool_use.json` fixture
- [x] **Backend** — `app/routes/hooks.py`, extended `app/routes/tickets.py`, tests
- [ ] **SDK** (`tentacle`) — no change in this ADR; tentacle parity comes in ADR 0008 (Phase C)
- [x] **Plugin** — full `packages/krakenops-claude-plugin/` scaffold + MCP server
- [x] **Dashboard** — minor styling tweak to surface `bind_method == "mcp"`; bulk of TODO rendering already landed in Phase A
- [ ] `scripts/e2e.sh` — add a synthetic hook POST that asserts the TODO list shows up on the next `workstreams` WS frame
- [ ] `CLAUDE.md` §10 roadmap — mark Phase B done

## Alternatives considered

- **Stuff the MCP server inside `apps/backend/`.** Rejected — coupling the
  user-facing plugin distribution to the backend's deps means a backend
  upgrade can break installed plugins. PEP 723 inline deps keep them
  independent; the plugin file declares exactly what `uv` should fetch.
- **Use SSE transport instead of stdio.** Rejected — stdio is the
  Claude-Code-native default; SSE adds an HTTP server inside the plugin
  process for no benefit when both ends are local.
- **Fold all four MCP tools into a single `krakenops.exec(command, …)` tool.**
  Rejected — generic exec tools deliberately give the agent a worse
  affordance signal; named tools with a typed body let Claude pick the
  right one without prompt-engineering.
- **Inject the session id via a request header on hook POSTs and have the
  MCP server read it from the same source.** Rejected — hooks and MCP run
  in different subprocesses with different IPC channels; a side channel
  through the local backend is what we already have. The heuristic
  fallback handles the common case.
