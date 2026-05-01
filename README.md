# KrakenOps

**Agent-Agnostic Command Center for Local AI Servers.**

A lightweight, local-first observability and orchestration layer for AI developers running agents on a single machine — typically a headless Mac mini or a beefy workstation.

Bring your own Python code. `pip install tentacle`, sprinkle in two decorators, and KrakenOps catches the spans, token usage, costs, and human-review pauses automatically. Everything runs on your machine — no hosted services, no rewrites into LangChain or CrewAI.

## What it does

- 📊 **Unified Dashboard** — live CPU/RAM/Disk gauges, running agent processes with token usage and cost in USD, and a Kanban board synced with GitHub Projects.
- 🐙 **`tentacle` SDK** — minimal Python decorators (`@tentacle.track_agent`, `@tentacle.tool`, `@tentacle.require_human`) built on OpenTelemetry. Bring your own code.
- 🔁 **Orchestration loop** — a FastAPI backend ingests OTel spans, samples hardware, and drives a GitHub Projects poller that spawns local agent processes and routes work back to humans when they pause.

## Status

Pre-alpha. Architecture finalized in [`CLAUDE.md`](CLAUDE.md). First runnable scaffold lands in PR #2 — see the roadmap at the bottom of `CLAUDE.md`.

## For contributors

Start with [`CLAUDE.md`](CLAUDE.md). It documents the three pillars, the workspace layout, the data flow, and the cross-repository change workflow. The repo also ships specialist Claude Code subagents and skills under `.claude/` — use them.

## License

MIT. See [LICENSE](LICENSE).
