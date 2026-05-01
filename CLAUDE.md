# KrakenOps

> **Agent-Agnostic Command Center for Local AI Servers.**
> Bring your own Python code. Sprinkle in two decorators. Get a live, beautiful operations dashboard for everything your local agents are doing.

This file is the canonical contract for how KrakenOps is built and how Claude Code should work in this repository. Read it before making non-trivial changes.

---

## 1. Project Vision

KrakenOps is a lightweight, **local-first** observability and orchestration layer for AI developers running agents on a single machine — typically a headless Mac mini or a beefy workstation. It targets the developer who wants real visibility into what their agents are doing **without rewriting their code into LangChain, CrewAI, or any other heavyweight framework**.

The animating principle is **"Bring Your Own Code"**: the user's Python script stays a Python script. They `pip install tentacle`, decorate a function or two, and our dashboard catches the spans, token usage, costs, and human-review pauses automatically. Everything runs on their machine. Nothing is sent to a hosted service unless the user explicitly wires one up.

KrakenOps takes its name from the metaphor of a Kraken's tentacles reaching into every running agent process — observing, never controlling. The SDK is therefore named **`tentacle`**.

---

## 2. The Three Pillars

KrakenOps is exactly three components, no more:

### 2.1 The Unified Dashboard — `apps/dashboard/`

A **Next.js 15 (App Router) + React 19 + Tailwind v4 + shadcn/ui** web UI that combines infrastructure and LLM telemetry on one page. Three panels:

- **Hardware Health** — live gauges for CPU, RAM, and Disk usage of the host machine (1 Hz updates).
- **Active Processes & Agents** — currently running agent processes with live console logs, tool-call traces, token usage, and per-call **cost in USD**.
- **The Kanban Queue** — a board synced with a GitHub Project showing which local agent is working on which ticket, what's done, and what's blocked.

State is managed with **TanStack Query** (REST cache) and **native `WebSocket`** (live streams). No Redux, no Zustand. Lint/format with **biome**.

### 2.2 The Agnostic SDK — `packages/tentacle/`

A tiny, standalone Python package built on **OpenTelemetry**. Public API:

```python
import tentacle

tentacle.init(endpoint="http://localhost:8787/v1/traces")

@tentacle.track_agent
def research_agent(topic: str) -> str:
    notes = gather_notes(topic)
    return summarize(notes)

@tentacle.tool
def gather_notes(topic: str) -> list[str]:
    ...

@tentacle.tool
def summarize(notes: list[str]) -> str:
    if needs_clarification(notes):
        raise tentacle.NeedsHumanReview(prompt="Ambiguous source — pick one.", payload={"options": [...]})
    ...
```

- Uses standard **OTLP/HTTP** to ship spans. The exporter is `opentelemetry-exporter-otlp-proto-http`.
- Auto-instruments OpenAI and Anthropic SDK calls (lazy import) to capture `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`.
- Cost is **not** computed in the SDK — only model + tokens. Cost math happens in the backend so users can override pricing without re-releasing the SDK.
- `tentacle.NeedsHumanReview` is a real exception: the user's code raises it, the backend catches its signature in the span tree and flips the GitHub ticket to "Needs Human Review".
- Dependency-light: no Pydantic, no httpx as a direct dep. Optional integrations live behind extras.

### 2.3 The Orchestration & Ticketing Loop — `apps/backend/`

A **FastAPI + SQLModel + uvicorn** server that does three things:

1. **Ingest OTel** at `POST /v1/traces`. Decode with `opentelemetry-proto`. Normalize into `traces`, `spans`, `token_usage`. **Derive cost** by joining `gen_ai.request.model` against the `model_pricing` table.
2. **Sample hardware** with `psutil` at 1 Hz, broadcast on the `metrics` WebSocket topic.
3. **Drive the Kanban loop**: a poller hits the **GitHub Projects v2 GraphQL API** every 30 s, mirrors items into the `tickets` table, and when a ticket transitions into "To-Do" it spawns the user-mapped agent script as a subprocess. When that subprocess emits a span tagged `tentacle.NeedsHumanReview`, the backend updates the GH ticket status to "Needs Human Review".

The backend is the **single source of truth** for GitHub state. The dashboard never talks to GitHub directly.

---

## 3. Workspace Structure (pseudo-monorepo)

```
KrakenOps/
├── apps/
│   ├── dashboard/          # Next.js 15 (App Router) + Tailwind + shadcn/ui
│   └── backend/            # FastAPI + SQLModel + psutil + WS
├── packages/
│   └── tentacle/           # Python SDK (uv-managed, publishable to PyPI)
├── examples/               # Sample agent scripts using tentacle
├── docs/
│   ├── adr/                # Architecture Decision Records (one file per contract change)
│   └── ...                 # Diagrams, tutorials
├── scripts/                # dev-up.sh, e2e.sh, seed.sh, release.sh
├── tests/
│   └── contract/           # Shared payload fixtures + JSON schemas
├── .claude/
│   ├── agents/             # Subagent definitions (sdk, backend, frontend, integrator)
│   ├── skills/             # Skill definitions (dev-up, seed-traces, release-tentacle)
│   └── settings.json
├── CLAUDE.md               # ← you are here
├── README.md
└── LICENSE
```

Each `apps/*` and `packages/*` carries **its own README and its own dependency manifest**. There is no root-level `package.json` or `pyproject.toml`. Every component is independently buildable and releasable.

---

## 4. Tech Stack & Conventions

| Component | Choice | Why |
|-----------|--------|-----|
| Frontend  | Next.js 15 App Router, React 19, Tailwind v4, shadcn/ui, TanStack Query, native `WebSocket` | Modern, opinionated, no extra state lib needed |
| Backend   | FastAPI, SQLModel (SQLAlchemy 2.x + Pydantic), uvicorn, psutil, httpx, opentelemetry-proto | Pydantic-native, async-friendly |
| SDK       | Python 3.10+, opentelemetry-api/sdk, OTLP/HTTP exporter | OTel is the universal standard |
| Storage   | SQLite (WAL mode) at `~/.krakenops/krakenops.db` | Local-first, zero ops |
| Realtime  | One WebSocket per client, multiplexed across topics: `metrics`, `traces`, `kanban` | One socket, three streams |
| Python tooling | **uv** for env + lockfile + scripts + publish | Fast, single tool |
| TS tooling | **pnpm** (or bun), **biome** for lint + format | Single fast tool for both |
| Lint (Py) | `ruff` | Fast, batteries-included |
| Tests (Py) | `pytest` | — |
| Tests (TS) | `vitest` | — |

**Naming & code style:**
- Python: `ruff` defaults, line length 100. Type hints required on public APIs.
- TS: `biome` defaults. Strict TS. No `any` outside narrow casts at IO boundaries.
- Files: `kebab-case.tsx` for components, `snake_case.py` for Python.
- API routes: lowercase, plural, prefixed with `/v1/`, e.g. `/v1/traces`, `/v1/agents`, `/v1/tickets`, `/v1/costs`.

**Versioning:**
- The SDK follows **SemVer** on PyPI under the distribution name `krakenops` (the Python module is `tentacle` — see [ADR 0004](docs/adr/0004-pypi-distribution-name.md)). Wire-format-affecting changes require a major bump. Releases are cut by pushing a `krakenops-v*` tag — see [docs/RELEASING.md](docs/RELEASING.md).
- Backend exposes `/v1/...` only. Breaking changes bump to `/v2/...` (and we maintain `/v1/` until the dashboard catches up).
- Dashboard is unversioned; it always ships with the backend revision in the same repo.

**Commit prefixes** (so `git log --grep` is useful):
- `sdk:` — anything in `packages/tentacle/`
- `backend:` — anything in `apps/backend/`
- `dashboard:` — anything in `apps/dashboard/`
- `docs:` — `docs/`, `README.md`, this file
- `infra:` — `scripts/`, `.claude/`, CI

---

## 5. Core Data Flow

Five flows tie the system together. Reviewers must understand all five.

### 5.1 SDK → Backend (telemetry ingest)

```
user_script.py
  └─ @tentacle.track_agent → opens OTel span (kind="agent")
       └─ @tentacle.tool   → child span (kind="tool")
            └─ openai.chat.completions.create(...)
                 ↳ auto-instrumentation captures gen_ai.* attrs
  ↓ batch export (OTLPSpanExporter, http/protobuf)
POST http://localhost:8787/v1/traces
  ↓ FastAPI route: app/routes/traces.py
opentelemetry-proto decode → normalized rows
  ↓
SQLite: traces, spans, token_usage
  ↓ on insert, lookup gen_ai.request.model in model_pricing
spans.cost_usd populated (NULL if model not priced; warn once)
  ↓
PubSub publish on "traces" topic → all subscribed WS clients
```

### 5.2 Hardware → Backend → Frontend

```
psutil.cpu_percent(interval=None) + virtual_memory() + disk_usage("/")
  ↓ background task, 1 Hz
MetricsSnapshot(cpu_pct, ram_pct, disk_pct, ts)
  ↓ PubSub publish on "metrics"
WebSocket broadcast → dashboard's <HardwarePanel />
```

### 5.3 Backend → Frontend (live traces)

```
new span row inserted (with cost_usd)
  ↓ PubSub publish on "traces"
WebSocket → dashboard's <ProcessesPanel />
  └─ shows agent name, span tree, tokens, cost, log lines
Historical fetch (paginated): GET /v1/traces?agent=...&since=...&limit=...
Cost rollups: GET /v1/costs?window=1h | 24h | 7d
```

### 5.4 GitHub Projects ↔ Backend (Kanban / orchestration loop)

```
poller (asyncio task, every 30 s, configurable POLL_INTERVAL)
  ↓ httpx → GitHub GraphQL: project items, fields, status
diff vs tickets table
  ↓ for each ticket transitioning into "To-Do":
       look up agent_script_path in agent_mappings table
       asyncio.create_subprocess_exec(python, script, *args)
       stream stdout/stderr line-by-line into per-agent log buffer
       (the SDK in that subprocess is already exporting to /v1/traces)
  ↓ on span observed with attribute "tentacle.needs_human_review = true":
       PATCH GitHub Project item: status → "Needs Human Review"
  ↓ PubSub publish on "kanban"
WebSocket → dashboard's <KanbanPanel />
```

### 5.5 Frontend → Backend (commands)

The dashboard issues commands via REST only:

- `POST /v1/agents/{id}/start` — manually spawn an agent.
- `POST /v1/tickets/{id}/resume` — clear "Needs Human Review", supply human-provided payload, resume the agent.
- `POST /v1/agents/{id}/stop` — terminate a running agent process.

WebSocket is **broadcast-only** (server → client). The frontend never writes via WS.

---

## 6. Cross-Repository Change Workflow

Because the three components share contracts, drift is the #1 thing that will quietly break KrakenOps. This workflow is non-negotiable for changes that touch a contract.

**A change is "cross-cutting" if it changes any of:**
- The OTel span attribute set the SDK emits.
- The shape of REST request/response bodies.
- The set of WS topics or the shape of messages on them.
- The schema of any SQLite table that the dashboard reads from indirectly via the API.

**For cross-cutting changes, the order is fixed:**

1. **ADR first.** Add `docs/adr/NNNN-short-name.md` describing the change, before any code. Use the template at `docs/adr/0000-template.md`.
2. **Schema doc / contract test.** Update fixtures in `tests/contract/` so the new shape is captured.
3. **Backend.** Implement ingestion / serving / migration.
4. **SDK.** Emit the new shape. Bump SDK version (major if breaking).
5. **Frontend.** Regenerate types from OpenAPI; consume the new field.

All five steps land in **one PR**, each as its own commit prefixed per §4.

**For non-contract changes** (internal refactors, UI tweaks, performance work) — no ADR needed, just the relevant component PR.

**Local verification before merging cross-cutting work:**
- `scripts/dev-up.sh` runs without errors.
- `scripts/e2e.sh` passes (runs `examples/hello_agent.py` against a freshly started backend, asserts span lands in DB and on the `traces` WS topic).
- The `integrator` subagent has reviewed the diff.

---

## 7. Local Development Quickstart

**Prereqs:** Python 3.10+, Node 20+, `uv`, `pnpm`. macOS (the primary target) or Linux. Windows is not supported.

### Option A — `docker compose up` (zero-install demo)

```sh
docker compose up
# → Dashboard  http://localhost:3000
# → Backend    http://localhost:8787  (REST + /v1/ws)
```

Backend image is built from `apps/backend/Dockerfile` (uv-based, multi-stage). Dashboard uses Next.js's `output: "standalone"` for a slim runtime. State persists in a named volume `krakenops_krakenops-data`; reset with `docker compose down --volumes`.

**Hardware metrics caveat:** `psutil` inside a container reports the container's view, not the host's — useful for proving the wiring works, but not the real intent of the Hardware panel. Use **Option B** for accurate host-level CPU/RAM/Disk.

### Option B — native (faster iteration, accurate hardware)

```sh
scripts/dev-up.sh
```
Boots backend on `:8787`, dashboard on `:3000`, and tails the example agent. Use the `/dev-up` skill if you'd rather Claude Code drive it.

Or one terminal each:
```sh
# Terminal 1 — backend
cd apps/backend && uv run uvicorn app.main:app --reload --port 8787

# Terminal 2 — dashboard
cd apps/dashboard && pnpm dev

# Terminal 3 — example agent
cd packages/tentacle && uv run python ../../examples/hello_agent.py
```

**State location (native mode):** `~/.krakenops/`
- `krakenops.db` — SQLite (WAL), all persistent state.
- `pricing.yaml` — optional override of the bundled model price list.
- `config.toml` — optional GH PAT, project ID, agent mappings.

Delete the directory to reset. Compose mode keeps the same files in a Docker volume mounted at `/data`.

---

## 8. Testing Strategy

**CI** runs on every PR + push to `main` via [`.github/workflows/ci.yml`](.github/workflows/ci.yml): SDK pytest+ruff, backend pytest+ruff, dashboard typecheck+biome+build. Three independent jobs in parallel.

- **Unit tests** live next to the code: `apps/backend/tests/`, `packages/tentacle/tests/`, `apps/dashboard/src/**/__tests__/`.
- **Contract tests** live at the repo root: `tests/contract/`. They contain canonical OTel payload fixtures + JSON schemas. Both backend and SDK test suites consume them — this is what catches wire-format drift before it ships.
- **End-to-end smoke** is `scripts/e2e.sh`: launches backend, runs `examples/hello_agent.py`, asserts a row in SQLite and a message on the `traces` WS topic. Used by CI and by the `integrator` subagent for cross-cutting PRs.

Local commands:
```sh
# Python
cd apps/backend && uv run pytest
cd packages/tentacle && uv run pytest

# TypeScript
cd apps/dashboard && pnpm test

# E2E
scripts/e2e.sh
```

---

## 9. Working with Claude Code in This Repo

This repo ships **four specialist subagents** and **three skills**. Use them.

### Subagents (under `.claude/agents/`)

| Agent | Owns | Use when |
|---|---|---|
| `sdk-engineer`     | `packages/tentacle/`              | Decorators, OTel exporters, auto-instrumentation, SDK release |
| `backend-engineer` | `apps/backend/`                   | Routes, SQLModel migrations, WS broker, psutil, GitHub poller |
| `frontend-engineer`| `apps/dashboard/`                 | Panels, hooks, TanStack Query, WS subscriptions, styling |
| `integrator`       | repo-wide, **read-only** + ADRs   | Cross-cutting PRs that change a contract |

The integrator is read-only on application code. If it spots a bug, it hands the precise file:line back to the relevant specialist.

### Skills (under `.claude/skills/`)

| Skill | What it does |
|---|---|
| `/dev-up`           | Run `scripts/dev-up.sh` and surface readiness signals |
| `/seed-traces`      | Fire `examples/hello_agent.py` N times so the dashboard has data |
| `/release-tentacle` | Bump version, build, publish (TestPyPI by default; PyPI on confirmation) |

### Working rules

- **Stay in your lane.** Specialist agents must not edit files outside their owned directory. Cross-cutting work goes to the human or the integrator.
- **Read the data flow (§5) before any non-trivial change.** Most bugs are violations of the flow, not bugs in the code.
- **An ADR is cheap.** When in doubt about whether a change is "cross-cutting", write the ADR — it forces clarity even if the answer turns out to be "no, this is internal".
- **Local-first or it doesn't ship.** No feature is allowed to require a hosted service to function.

---

## 10. Roadmap

KrakenOps is shipped in numbered PRs against `main`. The current state:

| PR | Scope | Status |
|----|-------|--------|
| #1 | This file + Claude Code metadata (subagents, skills) | **In review** (you're reading it) |
| #2 | Scaffold `apps/`, `packages/`, `examples/`, `scripts/`, `tests/contract/`. Stubs that build and pass empty tests. | Pending PR #1 approval |
| #3 | `tentacle` v0.1: `init`, `track_agent`, `tool`, `require_human`, OTLP/HTTP export, OpenAI auto-instrumentation. | Pending PR #2 |
| #4 | Backend v0.1: `/v1/traces` ingest, SQLite schema + migrations, `model_pricing` seed, REST list endpoints. | Pending PR #3 |
| #5 | Backend v0.2: psutil sampler + WS broker (`metrics`, `traces`). | Pending PR #4 |
| #6 | Dashboard v0.1: layout shell, Hardware panel, Processes panel against live WS + REST. | Pending PR #5 |
| #7 | Backend v0.3: GitHub Projects poller + agent subprocess orchestration + `kanban` WS topic. | Pending PR #6 |
| #8 | Dashboard v0.2: Kanban panel, command endpoints (`start`, `stop`, `resume`). | Pending PR #7 |
| #9 | v1.0 polish: dashboard cost rollup strip (`/v1/costs`), SDK 1.0.0, first PyPI release as **`krakenops`** (the `tentacle` PyPI name was already taken — see [ADR 0004](docs/adr/0004-pypi-distribution-name.md); Python module remains `tentacle`, Pillow-style). | **In review** |

Anything beyond PR #9 is post-1.0.
