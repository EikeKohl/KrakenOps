# ADR 0005: external OTel ingest + process discovery

- **Status:** Accepted
- **Date:** 2026-05-04
- **Deciders:** @eikekohlmeyer
- **Affects:** backend · dashboard · contract

## Context

KrakenOps today only sees agents that opt in via the `tentacle` SDK or that the GitHub Projects poller spawns. A growing fraction of real local-AI activity comes from tools that do **not** import `tentacle` — most prominently **Claude Code** (CLI + VS Code extension), but also Cursor, Continue, and similar editor-resident agents.

Constraints:
- **Local-first** (CLAUDE.md §1): no data leaves the host. The user is already running these tools locally; we just need to listen.
- **Bring-Your-Own-Code** is a one-way street: we cannot ask Claude Code to import our SDK. We meet it where it is.
- **No regression** of the existing three WS topics (`metrics`, `traces`, `kanban`) or the host-hardware sampler.

Two channels are available:
1. Claude Code emits **native OTLP/HTTP-protobuf** when `CLAUDE_CODE_ENABLE_TELEMETRY=1` is set, with `service.name=claude-code` as the resource attribute (see [docs](https://code.claude.com/docs/en/monitoring-usage)). It exports **metrics** (8 counters: `claude_code.token.usage`, `claude_code.cost.usage`, `claude_code.session.count`, …) and **logs/events** (17 event types: `claude_code.user_prompt`, `claude_code.api_request`, `claude_code.tool_result`, …) — but **not traces**. The richer signal is on logs.
2. The OS knows when these tools are running. `psutil` per-process iteration gives us name + PID + CPU% + RSS even when the user has not enabled telemetry.

We want **both**: process discovery as the always-on baseline, OTel ingest as the rich layer when the user wires up the env vars.

## Decision

### New REST endpoints

| Route | Body | Purpose |
|---|---|---|
| `POST /v1/metrics` | OTLP `ExportMetricsServiceRequest` (protobuf) | Ingest external OTel metrics. Persist to `external_metrics`, publish on `events` topic. |
| `POST /v1/logs`    | OTLP `ExportLogsServiceRequest` (protobuf)    | Ingest external OTel logs. Persist to `external_events`, publish on `events` topic. |
| `GET  /v1/processes` | — | Latest `discovered_processes` snapshot (REST seed for the dashboard). |
| `GET  /v1/events?service=&limit=&since=` | — | Historical event lookup. |

Both POST routes accept the same OTLP/HTTP-protobuf shape the existing `/v1/traces` route accepts (`Content-Type: application/x-protobuf`, raw body decoded with `opentelemetry-proto`). Auth + TLS are out of scope (local-first; same posture as `/v1/traces`).

### New WebSocket topics

`TOPICS = ("metrics", "traces", "kanban", "processes", "events")` — extend the tuple in [`app/realtime/bus.py:21`](../../apps/backend/app/realtime/bus.py#L21). The existing `metrics` topic is **unchanged** (host CPU/RAM/Disk at 1 Hz).

| Topic | Cadence | `data` shape |
|---|---|---|
| `processes` | 1 Hz | `{ processes: [{ pid, name, cmdline, cpu_pct, rss_mb, started_at_s }, …] }` |
| `events`    | per-record | One of `{kind: "metric", service_name, metric_name, value, unit, attributes}` or `{kind: "event", service_name, event_name, prompt_id?, session_id?, attributes, observed_at_ns}` |

### New tables (migration `003_external_telemetry.sql`)

```sql
CREATE TABLE external_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name    TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value           REAL NOT NULL,
    unit            TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    ts_ns           INTEGER NOT NULL
);
CREATE INDEX ix_external_metrics_service_ts ON external_metrics(service_name, ts_ns DESC);

CREATE TABLE external_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name    TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    prompt_id       TEXT,
    session_id      TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    observed_at_ns  INTEGER NOT NULL
);
CREATE INDEX ix_external_events_service_ts ON external_events(service_name, observed_at_ns DESC);
CREATE INDEX ix_external_events_prompt    ON external_events(prompt_id) WHERE prompt_id IS NOT NULL;

CREATE TABLE discovered_processes (
    pid           INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    cmdline       TEXT NOT NULL,
    last_cpu_pct  REAL NOT NULL DEFAULT 0,
    last_rss_mb   REAL NOT NULL DEFAULT 0,
    first_seen_ns INTEGER NOT NULL,
    last_seen_ns  INTEGER NOT NULL
);
```

### Allowlist config

Per-process sampler reads `KRAKENOPS_PROCESS_ALLOWLIST` (comma-separated, case-insensitive substrings matched against the joined cmdline). Default: `"claude"`. Empty → sampler disabled. `~/.krakenops/config.toml` may add a `[processes] allowlist = [...]` section that overrides the env var (parity with the existing GitHub config).

### Rendering

A new section group is added to the existing `ProcessesPanel` (no fourth panel — preserves CLAUDE.md §2 invariant):

1. Existing **SDK-tracked spans** (untouched).
2. **Discovered processes** — live table fed by the `processes` topic.
3. **External activity (Claude Code)** — events grouped by `prompt_id`, fed by the `events` topic.

## Consequences

### Positive
- Claude Code visibility with **zero changes to the user's agent code**.
- Process discovery works even without telemetry env vars — the user always sees *something* the moment they run Claude Code.
- All ingest reuses the OTLP/HTTP-protobuf path the backend already proves out for `/v1/traces`.
- Allowlist makes the same machinery generic for Cursor / Continue / future tools.

### Negative / accepted risks
- We special-case Claude Code attribute names (`prompt.id`, `session.id`) to populate the indexed `external_events.prompt_id` / `session_id` columns. Other OTel sources will land in `attributes_json` only. Acceptable: targeted, not generic.
- `external_metrics` does not feed `/v1/costs` in v1 (existing rollup FKs to `spans`). Cost rollup integration is a follow-up; raw cost data is queryable from `external_metrics` directly.
- `discovered_processes` rows accumulate across PIDs forever. We sweep rows whose `last_seen_ns` is older than 1 h on each sampler tick to bound table growth.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR; OTLP metrics + logs fixtures land in `tests/contract/`
- [x] **Backend** — migration 003, `app/sampler/processes.py`, `app/ingest/otel_metrics.py`, `app/ingest/otel_logs.py`, four new routes, bus topics, `main.py` wiring
- [ ] **SDK** (`tentacle`) — **no change** (this is purely an external-source ingest)
- [x] **Dashboard** — `DiscoveredProcessesSection`, `ExternalEventsFeed`, `ProcessesPanel` extension, types
- [x] `scripts/e2e.sh` — extended assertion that a synthetic OTLP-metrics POST lands on `events` WS
- [x] `CLAUDE.md` §5 — adds two new flow diagrams (process discovery; external OTel)

## Alternatives considered

- **Hooks-based ingestion.** Claude Code exposes HTTP hooks (`PreToolUse`, `PostToolUse`, `SessionStart`, …). Rejected for v1: hooks are designed for *blocking control*, not read-only observability. OTLP gives us the same data without inserting ourselves in Claude Code's critical path.
- **Spawn a separate OTel collector and forward to backend.** Rejected — adds an ops dependency that violates "local-first, zero ops" (CLAUDE.md §4).
- **Synthesize span rows from metrics/logs into the existing `spans` table.** Considered — would let us reuse `/v1/spans` and `/v1/costs` for free. Rejected because metrics are not span-shaped (gauge/counter values, no parent_span_id) and squeezing them in distorts both the schema and downstream UI semantics. Two new tables is the cleaner fit.
- **Generic OTel collector scope.** Rejected for v1 — we tailor ingest to known Claude Code metric/event names. Generalization comes when a second source actually shows up.
