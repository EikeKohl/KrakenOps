# KrakenOps Backend

FastAPI server: ingests OpenTelemetry traces from `tentacle`, samples hardware via `psutil`, fans out over WebSockets, and drives the GitHub Projects orchestration loop.

## Status

**v0.4.0** — adds operator-driven command endpoints (`spawn`, `stop`, `resume`) on top of v0.3's automatic poll-driven flow. See ADR 0003 for the contract. The v0.3 poller + orchestrator + `kanban` WS topic are unchanged; with no `~/.krakenops/config.toml` the poller is dormant and the rest of the backend (ingest, sampler, WS) works fine.

## Run

```sh
uv sync
uv run uvicorn app.main:app --reload --port 8787
```

On first start, the backend creates `~/.krakenops/krakenops.db`, applies migrations, seeds `model_pricing` from `pricing/default.yaml`, starts the `psutil` sampler, and (if configured) starts the GitHub poller.

For a containerized run alongside the dashboard, use `docker compose up` from the repo root — see [`../../CLAUDE.md`](../../CLAUDE.md) §7. The `Dockerfile` here is multi-stage (uv → slim runtime); state persists in a Docker volume mounted at `/data` (`KRAKENOPS_HOME=/data`).

## Endpoints

### REST

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/v1/health`             | Liveness probe |
| POST   | `/v1/traces`             | OTLP/HTTP protobuf ingest from `tentacle` |
| GET    | `/v1/traces`             | List recent traces (`?limit=50&since_ns=...`) |
| GET    | `/v1/traces/{trace_id}`  | One trace + full span tree |
| GET    | `/v1/spans`              | List spans (`?agent=...&kind=agent\|tool\|human_review&since_ns=...&limit=...`) |
| GET    | `/v1/costs`              | Cost rollup by model (`?window=1h\|24h\|7d`) |
| GET    | `/v1/tickets`            | GitHub Projects mirror (newest-updated first) |
| POST   | `/v1/tickets/{id}/spawn` | Manually run the configured agent for a ticket. **202** with `{run_id, agent}`; **404/409/400/503** per ADR 0003. |
| POST   | `/v1/tickets/{id}/resume`| Move a `Needs Human Review` ticket back to `Todo`. **200** with `{status: "Todo"}`. |
| GET    | `/v1/agents`             | Agent run history (`?status=running\|succeeded\|needs_human_review\|failed\|stopped`) |
| POST   | `/v1/agents/{run_id}/stop` | SIGTERM (then SIGKILL after 3 s grace) a running agent_run. Status becomes `stopped` (sticky). |

OpenAPI spec is live at `/docs` once the backend is running.

### WebSocket

`GET /v1/ws?topics=metrics,traces,kanban` — multiplexed broadcast.

| Topic | Payload `data` shape |
|------|---|
| `metrics` | `{ cpu_pct, ram_pct, disk_pct, ts_ns }` (1 Hz) |
| `traces`  | compact span summary on every `POST /v1/traces` ingest |
| `kanban`  | `{ tickets: [...] }` snapshot on every poll |

Wire envelope: `{ "topic": "...", "ts": <ns>, "data": ... }`.

## GitHub Projects orchestration

Optional. Configure via `~/.krakenops/config.toml`:

```toml
[github]
pat = "ghp_..."          # OR set env KRAKENOPS_GITHUB_PAT (env wins)
project_id = "PVT_..."   # GitHub Projects v2 node ID
poll_interval_s = 30

[[agents]]
name = "research"
script = "/abs/path/to/research_agent.py"
match_label = "research"     # null/missing = catch-all (first match wins)
args = ["--count", "1"]
env = { OPENAI_API_KEY = "sk-..." }
```

When a ticket transitions into `Todo`, the matching agent is spawned with these env vars added on top:

| Env | Value |
|---|---|
| `KRAKENOPS_TICKET_ID` | GitHub ProjectV2Item node ID |
| `KRAKENOPS_TICKET_TITLE` | ticket title |
| `TENTACLE_ENDPOINT` | this backend's `/v1/traces` URL |

Outcome classification (per ADR 0002):

| Exit code | Outcome | GitHub status set |
|---|---|---|
| `0`       | succeeded            | `Done` |
| `42`      | needs_human_review   | `Needs Human Review` |
| anything else | failed           | (untouched, operator follow-up) |

Use `sys.exit(42)` from inside an `except tentacle.NeedsHumanReview` block to signal a pause.

## Test

```sh
uv run pytest          # 66 tests
uv run ruff check .
```

End-to-end (SDK → backend → SQLite + WS broadcast) is exercised by `scripts/e2e.sh`. The e2e doesn't require GitHub credentials; the kanban path is exercised by unit tests against the `FakeGitHubClient`.

## State location

| Path | Purpose | Override |
|------|---------|----------|
| `~/.krakenops/krakenops.db`   | SQLite database (WAL mode)            | `KRAKENOPS_DB_PATH` |
| `~/.krakenops/pricing.yaml`   | User overrides for `model_pricing`    | — |
| `~/.krakenops/config.toml`    | GitHub PAT, project ID, agent mappings| `KRAKENOPS_GITHUB_PAT` (env-only PAT) |
| `~/.krakenops/`               | Root directory                        | `KRAKENOPS_HOME` |

Delete `~/.krakenops/` to reset.

## Layout

| Path | Purpose | Lands in |
|------|---------|----------|
| `app/main.py`              | FastAPI app, lifespan, routers              | PR #2/#4/#5/#7 |
| `app/config.py`            | env-driven paths (DB, pricing, migrations)  | PR #4 |
| `app/config_file.py`       | `~/.krakenops/config.toml` parser           | PR #7 |
| `app/routes/`              | health, traces, spans, costs, tickets, agents | PR #4/#7 |
| `app/ingest.py`            | OTLP decode + normalize per ADR 0001        | PR #4 |
| `app/db/`                  | engine, session, migrations runner, pricing | PR #4 |
| `app/realtime/bus.py`      | in-process pub/sub bus                      | PR #5 |
| `app/realtime/ws.py`       | `/v1/ws` multiplexed WebSocket endpoint     | PR #5 |
| `app/sampler/loop.py`      | psutil 1 Hz hardware sampler                | PR #5 |
| `app/poller/github.py`     | `GitHubClient` (real GraphQL + fake)        | PR #7 |
| `app/poller/loop.py`       | poll → upsert tickets → broadcast kanban    | PR #7 |
| `app/poller/orchestrator.py`| spawn agent subprocess + classify outcome  | PR #7 |
| `migrations/`              | versioned SQL applied at startup            | PR #4/#7 |
| `pricing/default.yaml`     | bundled model price list                    | PR #4 |

See [`../../CLAUDE.md`](../../CLAUDE.md) §2.3 + §5 for the full design, [ADR 0001](../../docs/adr/0001-tentacle-span-schema.md) for the span wire format, [ADR 0002](../../docs/adr/0002-orchestration-and-kanban.md) for the orchestration loop, and [ADR 0003](../../docs/adr/0003-command-endpoints.md) for the spawn / stop / resume commands.
