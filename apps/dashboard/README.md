# KrakenOps Dashboard

Next.js 15 (App Router) + React 19 + Tailwind v4 + TanStack Query.

The unified UI for KrakenOps: **Hardware Health · Active Processes & Agents · Kanban Queue**.

## Status

**v0.2.0** — all three panels are live: Hardware (psutil 1 Hz), Processes (REST seed + `traces` WS), Kanban (REST seed + `kanban` WS, status-grouped, with **Spawn** / **Resume** action buttons per card). Stop control on running agents is wired up to the backend's command endpoints (ADR 0003).

## Run

```sh
pnpm install
pnpm dev          # → http://localhost:3000
```

The dashboard reads `NEXT_PUBLIC_KRAKENOPS_API` (default `http://localhost:8787`) for both REST and WebSocket targets. Note: this is a `NEXT_PUBLIC_*` var, so it's **inlined at build time**, not read at runtime — for the Docker build, pass it via `--build-arg` (see `compose.yml`).

For a containerized run, use `docker compose up` from the repo root. The `Dockerfile` here is multi-stage and produces a minimal runtime via Next.js's `output: "standalone"`.

For a fully populated dashboard, run the backend + an example agent so traces stream in:

```sh
# terminal 1
( cd apps/backend && uv run uvicorn app.main:app --port 8787 )

# terminal 2 — seed traces
( cd packages/tentacle && uv run python ../../examples/hello_agent.py --count 10 \
    --endpoint http://127.0.0.1:8787/v1/traces )

# terminal 3
( cd apps/dashboard && pnpm dev )
```

## Verify

```sh
pnpm run typecheck
pnpm run biome:check
pnpm run build
```

## Layout

| Path | Purpose | Lands in |
|------|---------|----------|
| `src/app/layout.tsx`              | Root HTML/CSS shell + `<Providers>` | PR #2 / #6 |
| `src/app/page.tsx`                | Three-panel grid | PR #6 |
| `src/app/globals.css`             | Tailwind v4 entry + theme tokens | PR #2 |
| `src/lib/api.ts`                  | Typed REST client (single source of truth) | PR #6 |
| `src/lib/ws.ts`                   | Multiplexed WS client + `useLatestMessage` / `useTopicListener` hooks | PR #6 |
| `src/lib/queryClient.ts`          | TanStack QueryClient factory | PR #6 |
| `src/lib/format.ts`               | Cost / time / duration formatters | PR #6 |
| `src/types/api.ts`                | Backend payload types (eventually OpenAPI-generated) | PR #6 |
| `src/components/Providers.tsx`    | `QueryClientProvider` wrapper | PR #6 |
| `src/components/Panel.tsx`        | Shared panel chrome (border, header, body) | PR #6 |
| `src/components/Gauge.tsx`        | Color-blind-safe horizontal gauge | PR #6 |
| `src/components/HardwarePanel.tsx`| CPU / RAM / Disk live from `metrics` topic | PR #6 |
| `src/components/SpanRow.tsx`      | Single-line span renderer (kind badge + cost + duration) | PR #6 |
| `src/components/ProcessesPanel.tsx`| REST-seed + WS-live span feed | PR #6 |
| `src/components/KanbanPanel.tsx`  | Live ticket mirror — REST seed + `kanban` WS, grouped by status | PR #8 |
| `src/components/TicketCard.tsx`   | Single ticket row + Spawn / Resume mutations | PR #8 |

## Live data flow

- `<HardwarePanel>` subscribes to the `metrics` topic via `useLatestMessage<MetricsSnapshot>` — re-renders ~1 Hz with the backend's `psutil` snapshot.
- `<ProcessesPanel>` runs `useQuery(['spans', 'recent'])` on mount (REST `GET /v1/spans?limit=50`), then `useTopicListener('traces', ...)` prepends new spans as the backend ingests them. Dedup by `span_id`.
- `<KanbanPanel>` runs `useQuery(['tickets'])` on mount, then `useTopicListener('kanban', ...)` replaces the list on every poll snapshot. **Spawn** and **Resume** buttons issue `POST /v1/tickets/{id}/spawn` and `/resume` via TanStack Query mutations and invalidate the relevant queries on success.
- Single shared WebSocket per browser session (`getWSClient()`); auto-reconnects with exponential backoff (500 ms → 15 s cap).

shadcn/ui is **not** initialized yet — when the first shadcn component is needed (likely PR #8 for the Kanban board), run `pnpm dlx shadcn@latest init` from this directory.

See [`../../CLAUDE.md`](../../CLAUDE.md) §2.1 + §5 for the full design.
