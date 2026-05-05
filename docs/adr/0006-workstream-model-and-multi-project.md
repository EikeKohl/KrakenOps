# ADR 0006: workstream model + multi-project poller

- **Status:** Accepted
- **Date:** 2026-05-05
- **Deciders:** @eikekohlmeyer
- **Affects:** backend · dashboard · contract

## Context

KrakenOps's data model up to ADR 0005 makes it possible to *see* a Claude
Code session's events and the host processes it spawns, but it cannot answer
the question the dashboard is supposed to answer:

> "**Which agent** is right now working on **which ticket** in **which
> project**, what's their current TODO list, and how much have they spent?"

Three constraints land here at once:

1. **Multi-project mirroring.** Today's poller takes one
   `[github] project_id` and the `tickets` table stores a flat global list.
   The user has multiple Projects v2 boards (one per repo / area) and wants
   to see all of them at once, **grouped by project**.
2. **Read-only stance.** Per the latest product call, KrakenOps no longer
   spawns agent subprocesses on `Todo` transitions. Whatever's already
   running on the host (Claude Code CLI, a `tentacle`-instrumented script, …)
   is what we observe. The user (or the agent itself, via an MCP tool we
   ship in a follow-up) chooses what to bind to which ticket.
3. **Workstream as the unifying noun.** Spans, external events, agent_runs,
   discovered processes — all describe pieces of the same thing: a single
   AI workstream the user cares about. We need an explicit table for it so
   the dashboard can pivot from "live event firehose" to
   "card-per-workstream with bound ticket + TODO progress + cost".

`agent_runs` partly fills role (3) but is wrong-shaped: it's keyed on
ticket+spawn, has no notion of an unbound running agent, and carries the
spawned-subprocess lifecycle (pid, exit code, stderr_tail) that doesn't
apply to a user-launched Claude Code session. Reusing it would force every
Claude Code session into a fake `started_at_s` / `pid` / `exit_code`
shape. Cleaner to introduce a sibling.

## Decision

### Workstream

Every observable piece of AI work on the host is a **workstream**. Sources
in v1: `claude_code` (auto-discovered from `/v1/logs` ingest by `session.id`),
`tentacle` (auto-discovered from `/v1/traces` by `trace_id` plus a
`krakenops.workstream.session_id` resource attribute), and `manual` (user
created an entry in the dashboard with no telemetry — out of scope for v1
but the schema accepts it).

```sql
CREATE TABLE workstreams (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source             TEXT    NOT NULL,    -- "claude_code" | "tentacle" | "manual"
    external_id        TEXT,                -- session.id (claude) or trace root id (tentacle)
    label              TEXT,                -- human label, e.g. "Claude Code · sess a8b6"
    ticket_id          TEXT REFERENCES tickets(id),
    project_id         TEXT REFERENCES projects(id),
    bind_method        TEXT,                -- "mcp" | "manual" | "auto" | NULL
    started_at_s       INTEGER NOT NULL,
    last_seen_at_s     INTEGER NOT NULL,
    ended_at_s         INTEGER,
    todos_json         TEXT NOT NULL DEFAULT '[]',
    todos_updated_at_s INTEGER
) STRICT;
CREATE UNIQUE INDEX ux_workstreams_ext  ON workstreams(source, external_id);
CREATE INDEX idx_workstreams_ticket    ON workstreams(ticket_id);
CREATE INDEX idx_workstreams_last_seen ON workstreams(last_seen_at_s DESC);
```

`todos_json` is a flat JSON array `[{content, activeForm, status}]` —
mirrors Claude Code's `TodoWrite` payload and the `tentacle.set_todos`
shape (see ADR 0007). Whole-list rewrite per update; no child table.

### Projects

```sql
CREATE TABLE projects (
    id              TEXT    PRIMARY KEY,    -- GitHub ProjectV2 node id
    title           TEXT    NOT NULL,
    owner_login     TEXT    NOT NULL,
    last_seen_at_s  INTEGER NOT NULL
) STRICT;

ALTER TABLE tickets ADD COLUMN project_id TEXT REFERENCES projects(id);
CREATE INDEX idx_tickets_project ON tickets(project_id);
```

`project_id` is **nullable** so the migration is non-breaking for users on
existing single-project installs; the multi-project poller backfills the
column on first tick.

### Multi-project config

`apps/backend/app/config_file.py` accepts `[[github.projects]]` blocks:

```toml
[github]
pat = "ghp_…"                  # one PAT, owner of all listed projects
poll_interval_s = 30           # default applies to projects without override

[[github.projects]]
id = "PVT_kwDO…backend"

[[github.projects]]
id = "PVT_kwDO…frontend"
poll_interval_s = 60           # per-project override (optional)
```

Legacy `[github] project_id = "…"` keeps working — it's read as a single
implicit `[[github.projects]]` entry. No flag day.

The poller spawns one async tick task per project. Tick rate is per-project
so a slow board doesn't block a fast one. Each task instantiates its own
`GitHubGraphQLClient` (which is already parameterized on project_id —
ADR 0002).

**No more auto-spawn.** The `do_dispatch` / `run_agent` /
`agent_mappings.match_label` machinery in `app/poller/loop.py` and
`app/poller/orchestrator.py` no longer fires on a `Todo` transition. The
orchestrator file stays for the manual `/v1/tickets/{id}/spawn` endpoint
(unchanged from ADR 0003) which we'll deprecate cleanly in a follow-up.

### Workstream auto-discovery

A new module `app/workstreams/` runs as a lifespan-owned subscriber on the
existing `events` pub/sub topic (ADR 0005). On each frame:

- `kind == "event"` and `service_name == "claude-code"` and a
  `session.id` attribute is present → upsert a row keyed
  `(source="claude_code", external_id=session.id)`. First sighting sets
  `started_at_s`, every sighting bumps `last_seen_at_s`. Label: `"Claude
  Code · sess <first 8 chars>"`.
- `kind == "metric"` likewise.

A second subscriber on the `traces` topic does the same for
`tentacle` workstreams when a span carries
`krakenops.workstream.session_id` (which the SDK will start emitting in
Phase C — ADR 0007). Until then this branch is dormant.

### REST + WS surface

| Method | Path                                  | Body / Response                                                              |
| ------ | ------------------------------------- | ---------------------------------------------------------------------------- |
| GET    | `/v1/projects`                        | `{projects: [{id, title, owner_login, last_seen_at_s}]}`                     |
| GET    | `/v1/workstreams`                     | `{workstreams: [{id, source, external_id, label, ticket_id, project_id, bind_method, started_at_s, last_seen_at_s, ended_at_s, todos: [...]}]}` |
| POST   | `/v1/workstreams/{id}/bind`           | `{ticket_id, project_id?}` → `{bound: true, bind_method: "manual"}`          |
| POST   | `/v1/workstreams/{id}/unbind`         | `→ {bound: false}`                                                           |

The existing `/v1/tickets` response gains a `project_id` field (nullable
during the migration window).

New WS topic: `workstreams`. Cadence: per change (auto-discovery upsert,
bind/unbind, ended). Payload is a full snapshot of currently-active
workstreams (those with `ended_at_s IS NULL` or
`last_seen_at_s` within the last 5 min): `{workstreams: [...]}`. Same
"replace local state" pattern the dashboard already uses for `processes`
and `kanban`.

`TOPICS = ("metrics", "traces", "kanban", "processes", "events", "workstreams")`
in `app/realtime/bus.py:21`.

## Consequences

### Positive
- The dashboard can finally show "agent X working on ticket Y in project Z"
  as a first-class concept, not a join chain.
- Multi-project comes for free in the API: every workstream and every
  ticket carries a `project_id`. No N+1 lookup at render time.
- Auto-discovery means the user sees a workstream card the moment a
  Claude Code session starts — zero plugin install required for v1
  visibility. The plugin in ADR 0007 just adds the bind+TODO layer on top.
- Dropping auto-spawn lets us delete a tricky-to-test code path (subprocess
  exec, label matching, status transitions) and aligns the product with the
  "monitoring tool" framing.

### Negative / accepted risks
- A workstream stays "active" until `last_seen_at_s` falls 5 min in the
  past. There's no explicit "session ended" signal in v1 (Claude Code
  doesn't emit one over OTel, and `SessionEnd` hooks come with the plugin
  in ADR 0007). Accepted — stale rows just slide out of the active list.
- `bind_method=mcp` rows from the future plugin and `manual` rows from the
  dashboard share the same column. Tracking which is fine; the value is
  informational, not authoritative. We do not enforce a state machine
  (manual unbind → mcp re-bind allowed).
- Cost-per-ticket needs a join from `external_events.session_id` /
  `spans.trace_id` → `workstreams.external_id` → `workstreams.ticket_id`.
  We add a `cost_by_ticket` view at materialization time, not a stored
  column, so it stays accurate as bindings change.
- Removing the auto-spawn path is a behavior change: any user who relied
  on `agent_mappings` to dispatch a script when a ticket entered Todo
  loses that. Documented in CHANGELOG; the manual
  `POST /v1/tickets/{id}/spawn` endpoint still works.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR; new `workstream.schema.json`
  + `project.schema.json` in `tests/contract/schemas/`
- [ ] **Backend** — migration 004, `app/workstreams/` module, three new
  routes, multi-project poller, `main.py` lifespan wiring
- [ ] **SDK** (`tentacle`) — no change in this ADR; the
  `krakenops.workstream.session_id` resource attribute lands in ADR 0007
- [ ] **Dashboard** — `WorkstreamsPanel`, `WorkstreamCard`,
  `WorkstreamBindModal`, `ProjectTabs`; types regenerated; new layout
- [ ] `scripts/e2e.sh` — assert a synthetic Claude Code log POST creates
  a workstream row that shows on the `workstreams` WS topic
- [ ] `CLAUDE.md` §5 — replace the "GitHub poller spawns agent" flow
  with "GitHub poller mirrors → workstream binds → status pushes back"

## Alternatives considered

- **Reuse `agent_runs` for all workstreams.** Rejected: its
  pid/exit_code/stderr_tail columns don't apply to user-launched Claude
  Code sessions, and its primary key (`id INTEGER`) makes it awkward to
  upsert by external session id. A new table is structurally simpler.
- **Per-TODO-item child table.** Rejected: TodoWrite always rewrites the
  whole list, so a child table buys nothing but write amplification and
  delete-then-insert cycles per update.
- **Multi-project as `[github.<key>]` sections (one TOML table per
  project).** Rejected: dynamic key names break the AgentConfig pattern
  and complicate the wizard. `[[github.projects]]` is a standard TOML
  array of tables and round-trips cleanly through the
  multi-select picker `list_user_projects` already returns.
- **Keep auto-spawn as an opt-in.** Rejected for v1 — keeping a code path
  alive purely for backward compatibility violates CLAUDE.md "no
  half-finished implementations" and would force every workstream test
  to mock the subprocess code. Manual spawn endpoint is the escape hatch.
