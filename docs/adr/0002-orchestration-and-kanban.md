# ADR 0002: orchestration loop, tickets schema, and kanban WS payload

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** @eikekohlmeyer
- **Affects:** backend · dashboard · contract

## Context

PR #7 wires the **orchestration loop** described in CLAUDE.md §5.4: a backend
poller mirrors a GitHub Projects v2 board into SQLite, spawns local agent
subprocesses for tickets that enter `Todo`, and reports back to GitHub when an
agent run completes or pauses for human review. This ADR pins the schema, the
WS payload, and the contract between the orchestrator and the user's agent
script — those are the surfaces the dashboard and downstream tooling depend on.

Constraints:

- **Local-first.** The PAT lives only on the backend; the dashboard never
  touches GitHub directly (CLAUDE.md §2.3, §5.4).
- **Optional GitHub.** A user with no PAT must still get a working backend
  and dashboard — the poller stays dormant, no errors.
- **Polling, not webhooks.** A headless Mac mini behind NAT can't receive
  webhooks. 30 s default interval, configurable.
- **Ticket ↔ agent linkage stays simple.** v0.3 uses **process exit code +
  stderr inspection** to classify the outcome (success / human review /
  failure). A richer link (SDK-level `krakenops.ticket_id` resource attribute)
  is deferred to a later ADR.

## Decision

### Configuration file: `~/.krakenops/config.toml`

```toml
[github]
pat = "ghp_..."          # OR set via env KRAKENOPS_GITHUB_PAT (env wins)
project_id = "PVT_..."   # GitHub Projects v2 node ID
poll_interval_s = 30     # default 30, min 5

# Zero or more agent mappings. First match wins.
[[agents]]
name = "research"
script = "/abs/path/to/research.py"   # relative paths resolved against KRAKENOPS_HOME
match_label = "research"               # null/missing = catch-all
args = ["--count", "1"]
env = { OPENAI_API_KEY = "sk-..." }
```

Missing file → poller dormant. Missing `[github]` block → poller dormant.
Missing `[[agents]]` → poller still mirrors tickets; just doesn't spawn anything.

### New SQL tables (migration 002)

```sql
CREATE TABLE tickets (
    id              TEXT PRIMARY KEY,           -- GitHub ProjectV2Item node ID
    title           TEXT NOT NULL,
    status          TEXT NOT NULL,              -- "Todo" | "In Progress" | "Needs Human Review" | "Done" | <unknown>
    url             TEXT,
    agent           TEXT,                       -- agent name currently assigned (null if none)
    updated_at_s    INTEGER NOT NULL,
    last_seen_at_s  INTEGER NOT NULL            -- last poll observation; deletes detected via gap
);

CREATE TABLE agent_mappings (
    name          TEXT PRIMARY KEY,
    script_path   TEXT NOT NULL,
    match_label   TEXT,                          -- null = catch-all
    args_json     TEXT NOT NULL DEFAULT '[]',
    env_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    pid             INTEGER,
    started_at_s    INTEGER NOT NULL,
    ended_at_s      INTEGER,
    status          TEXT NOT NULL,               -- "running" | "succeeded" | "needs_human_review" | "failed"
    exit_code       INTEGER,
    stderr_tail     TEXT
);
```

### `kanban` WS payload

Server emits the **full ticket snapshot** on every poll (and once on startup).
Client just replaces its in-memory list — no diff logic needed.

```json
{
  "topic": "kanban",
  "ts": 1735689600000000000,
  "data": {
    "tickets": [
      {
        "id": "PVTI_...",
        "title": "Investigate cache miss rate",
        "status": "Todo",
        "url": "https://github.com/owner/repo/issues/42",
        "agent": "research",
        "updated_at_s": 1735689000
      }
    ]
  }
}
```

### Subprocess contract

When the poller decides to run an agent for a ticket, it spawns:

```
<configured-script> <configured-args...>
```

with these env vars added on top of the parent process:

| Env | Value |
|---|---|
| `KRAKENOPS_TICKET_ID` | GitHub ProjectV2Item node ID |
| `KRAKENOPS_TICKET_TITLE` | ticket title |
| `TENTACLE_ENDPOINT` | `http://127.0.0.1:<backend-port>/v1/traces` |

**Outcome classification** (read after exit):
- exit code `0` → `succeeded` → GitHub status set to `Done`.
- exit code `42` (sentinel) → `needs_human_review` → GitHub status set to `Needs Human Review`.
- any other non-zero → `failed` → GitHub status untouched (operator-driven).

`tentacle.NeedsHumanReview` is *re-raised* by the SDK (see ADR 0001). For v0.3
we ask agent scripts to translate that to exit code 42 themselves — typically
with a one-line `try / except / sys.exit(42)`. A future SDK helper
(`tentacle.run_as_agent(...)`) will hide this boilerplate.

## Consequences

### Positive
- Dashboard gets a coherent kanban panel with one WS subscription + one REST
  endpoint — no GitHub OAuth, no token in the browser.
- Operator can run KrakenOps fully locally with zero GitHub config; the
  Hardware + Processes panels still light up.
- Schema is stable: tickets is mirror-only, agent_runs is append-only —
  re-running the poller is safe.

### Negative / accepted risks
- Exit-code-42 sentinel is a hack. Documented; superseded once the SDK ships
  `run_as_agent`.
- Polling means up to `poll_interval_s` of latency on status changes.
  Acceptable for human-in-the-loop work; webhooks are a future concern.
- The `kanban` payload sends the whole ticket list each poll. Cheap when
  N < 1000; will need delta encoding past that.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR + migration 002.
- [x] **Backend** — poller, orchestrator, GitHub client (real + fake), routes.
- [ ] **SDK** — defer (no contract change in this PR).
- [ ] **Dashboard** — `<KanbanPanel>` consumes `kanban` topic + `GET /v1/tickets` → PR #8.
- [x] `scripts/e2e.sh` — still passes; kanban assertion is opt-in, gated on
      a configured backend.
- [x] `CLAUDE.md` §5.4 — still accurate; the SDK-level ticket linkage caveat
      is captured here.

## Alternatives considered

- **GitHub webhooks instead of polling.** Rejected — local-first means we
  can't expose an inbound endpoint without ngrok/cloud relay.
- **SDK-level `krakenops.ticket_id` resource attribute.** Better long-term
  design; deferred until v0.3 is in users' hands and we have feedback on
  whether process-exit semantics are sufficient.
- **Single GitHub client (no fake).** Rejected — would force tests to either
  hit the real API or grow elaborate HTTP mocks. The interface is small.
