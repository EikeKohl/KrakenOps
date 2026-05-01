# Contract tests

This directory holds the **shared, language-neutral fixtures** that pin the wire format between the three KrakenOps components:

- `tentacle` (Python SDK) — emits these payloads
- `apps/backend` (FastAPI) — ingests these payloads
- `apps/dashboard` (Next.js) — renders the resulting normalized data

Both the backend test suite and the SDK test suite load fixtures from this directory. When the wire format changes, the fixture changes here **first**, per [`../../CLAUDE.md`](../../CLAUDE.md) §6 ("Cross-Repository Change Workflow").

## Layout

| File | Purpose | Lands in |
|------|---------|----------|
| `otel_spans.minimal.json`        | Smallest valid payload representing one agent + one tool span | PR #3 |
| `otel_spans.with_tokens.json`    | Adds `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` / `gen_ai.request.model` | PR #3 |
| `otel_spans.human_review.json`   | A span tree where the inner tool raises `tentacle.NeedsHumanReview` | PR #3 |
| `pricing.snapshot.yaml`          | The seeded model price list backend joins against; regenerate when prices change | PR #4 |
| `schemas/tentacle_span.schema.json` | JSON Schema fixtures are validated against in CI | PR #3 |

## Format note

Fixtures use a **simplified human-readable JSON** — closer to what the backend stores than to raw OTLP/protobuf. The SDK emits OTLP/HTTP, the backend decodes with `opentelemetry-proto`, and from that decoded form the data should match these fixtures structurally. A converter `tests/contract/_convert.py` lands alongside the backend ingest code in PR #4.

The canonical span schema is **ADR 0001** ([`../../docs/adr/0001-tentacle-span-schema.md`](../../docs/adr/0001-tentacle-span-schema.md)).
