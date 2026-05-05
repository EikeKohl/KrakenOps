# ADR 0008: tentacle SDK parity + cost-by-ticket

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @eikekohlmeyer
- **Affects:** sdk · backend · dashboard

## Context

ADR 0006 introduced the workstream model and ADR 0007 wired Claude Code
into it via a plugin (hooks + MCP). What's missing for the v1 vision:

1. **Tentacle SDK parity.** A user-launched Python script using
   `@tentacle.track_agent` + `@tentacle.tool` shows up as a workstream
   only if we extend auto-discovery beyond the Claude Code branch — and
   it has no way to claim a ticket, push status back, or publish a TODO
   list. The plugin's MCP server exposes these for Claude Code; there's
   no symmetric path for tentacle agents.
2. **Cost-by-ticket.** The dashboard's `/v1/costs` endpoint groups by
   model. The vision wants per-ticket spend on each Kanban card so the
   user can see "this ticket's already burned $4.20" without leaving the
   page.

Both of these hinge on linking telemetry rows back to the workstream that
produced them. For Claude Code that linkage already exists: the
`external_events` / `external_metrics` rows carry `session.id` in their
`attributes_json` blob, and the workstream is keyed
`(source="claude_code", external_id=session.id)`. For tentacle agents we
need a parallel handle.

## Decision

### SDK additions (tentacle v0.2.0)

Three new public functions plus one bootstrap call:

```python
import tentacle

tentacle.init(endpoint="http://localhost:8787/v1/traces")

# Optional but recommended at the top of the script — registers the
# workstream so the agent's spans + signals get attributed correctly.
tentacle.register_workstream(label="research run #42")

@tentacle.track_agent
def research(topic: str) -> str: ...

# At any point during the run:
tentacle.claim_ticket("PVTI_lAHO…")          # bind to a ticket
tentacle.set_todos([                         # publish a checklist
    {"content": "Fetch sources", "status": "completed"},
    {"content": "Summarize",     "status": "in_progress"},
])

# When ready for review:
tentacle.set_status("PVTI_lAHO…", "Needs Human Review")
```

**`register_workstream(label=None) -> str`** — generates a
session id (uuid4) if not supplied, POSTs `{source: "tentacle",
external_id, label}` to `/v1/workstreams/register`, and stashes the id
in module-level state so the rest of the SDK can use it implicitly.
Returns the id so the caller can pass it through subprocesses if it
fans out work.

**`claim_ticket / set_status / set_todos`** — same shape as the MCP
tools (ADR 0007), implemented as `httpx.post` against the existing
`/v1/workstreams/claim`, `/v1/tickets/{id}/status`,
`/v1/workstreams/todos` routes. They fall through to the backend's
heuristic resolver when no session id has been registered yet — same
single-session affordance as the MCP path.

The new module is `packages/tentacle/src/tentacle/_status.py`. Module
state is a module-level `_session_id: str | None`; thread-safe by
necessity is *not* a goal in v0.2 — agents that fork into multiple
sessions per process should call `register_workstream` per child.

### Backend additions

**`POST /v1/workstreams/register`** body
`{source, external_id, label}` →
`{workstream_id, source, external_id}`. Idempotent on
`(source, external_id)`. Lets *any* SDK or non-Claude agent bootstrap
a workstream that the dashboard then sees as soon as the next
`workstreams` snapshot publishes. The Claude Code plugin doesn't need
this (its hook flow already creates rows) but `tentacle` and future
sources do.

**`/v1/costs?group_by=ticket`** — new query mode on the existing
endpoint. Returns

```json
{
  "window": "24h",
  "by_ticket": [
    {"ticket_id": "PVTI_…", "ticket_title": "Add billing webhook",
     "project_id": "PVT_backend", "project_title": "Backend",
     "cost_usd": 0.84, "calls": 12}
  ],
  "total_cost_usd": 0.84
}
```

For Claude Code the rollup joins `external_metrics` (where
`metric_name = 'claude_code.cost.usage'`) by `attributes_json ->
'session.id'` to `workstreams.external_id` to `workstreams.ticket_id`.
v1 ships this path only — `tentacle` cost-by-ticket needs span↔workstream
linkage which depends on a future migration that adds
`workstream_session_id` to the `traces` table; called out in
"Negative / accepted risks". `by_ticket` rows for tentacle workstreams
will simply have `cost_usd = 0` until then.

### Dashboard additions

`TicketCard` gains a small `$x.xx` chip in its footer when the
backend returns a non-zero cost for the ticket. The chip is fed by a
`useQuery(["costs", "by-ticket"])` hook that polls `/v1/costs?group_by=ticket`
every 60 s — same cadence as the existing 24 h totals strip in the
header.

No layout shifts; the chip sits next to the existing "→ agent name"
line and stays out of the way when zero.

## Consequences

### Positive
- `tentacle`-instrumented agents finally get the same affordance Claude
  Code has — a card that lights up with TODOs, a binding to a ticket,
  and status push-back. Symmetric SDK feels intentional.
- Cost-by-ticket lands the most-asked-for "where's my money going"
  rollup against the data we already collect, without a schema
  migration.
- `/v1/workstreams/register` becomes the future hook point for any new
  agent runtime — Cursor, Continue, custom Go SDKs, etc. We don't have
  to re-invent auto-discovery per source.

### Negative / accepted risks
- The `tentacle.set_*` calls are HTTP-direct, not OTel-span based.
  That means a process running tentacle without network access to the
  backend silently no-ops the status calls. Acceptable for v1 — `init()`
  already takes the same endpoint, so if traces work, these will too.
  Errors are logged but never raised, so user agent code keeps running.
- Cost-by-ticket for *tentacle* workstreams is `0` until the
  trace↔workstream linkage lands in a follow-up ADR (likely 0009 with
  a tiny migration adding `traces.workstream_session_id` and ingest
  to populate it from a span resource attribute). Documented in the
  endpoint response and the dashboard chip ("—" when cost is 0 and
  source is tentacle).
- The SDK's module-level session state means a single Python process
  cannot run two workstreams concurrently. v1 limitation; the explicit
  `session_id` parameter on each call is the escape hatch.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR (no schema migration in v1)
- [x] **Backend** — `POST /v1/workstreams/register`, extended
  `/v1/costs` with `group_by=ticket`, tests
- [x] **SDK** (`tentacle`) — `_status.py` module + 4 new public exports;
  bumped to v0.2.0
- [x] **Dashboard** — TicketCard cost chip + new `costs?group_by=ticket`
  query helper
- [ ] `scripts/e2e.sh` — assert the example agent's `set_todos` lands
  on the bound ticket's workstream card
- [x] `examples/hello_agent.py` — demonstrate `register_workstream`,
  `claim_ticket`, `set_todos`

## Alternatives considered

- **Make `tentacle.set_status / set_todos` emit a magic OTel span the
  backend recognizes.** Rejected — would require extending the traces
  ingest path with a side-effect codepath, blurring the line between
  observability and command. HTTP POST is honest about the intent.
- **Auto-register on first decorated call.** Considered: any
  `@track_agent` invocation could implicitly call `register_workstream`
  if it hasn't run yet. Rejected for v1 because it makes the
  network-dependency surprise (a decorated function suddenly hits the
  backend). Explicit `register_workstream` keeps the contract
  predictable. We can revisit once the OTel-span path lands.
- **Compute cost-by-ticket in the dashboard from the workstreams +
  events streams.** Rejected — the dashboard already does enough
  aggregation; pushing this to the backend keeps the WS frame small and
  lets us add caching later without touching the UI.
