# ADR 0001: tentacle span schema

- **Status:** Accepted
- **Date:** 2026-04-30
- **Deciders:** @eikekohlmeyer
- **Affects:** sdk · backend · contract

## Context

PR #3 ships the first real `tentacle` v0.1: actual OpenTelemetry span emission, not no-op stubs. Before any code lands we need to lock the **span schema** — names, attributes, and signal patterns the SDK emits — because every other component (backend ingest, dashboard rendering, contract fixtures) is downstream of this choice.

Constraints:
- **OTel-native.** Stay on standard semantic conventions wherever they exist. Custom attributes only where there is no standard.
- **Multi-vendor friendly.** A user who points `tentacle` at Honeycomb or Jaeger instead of our backend should still see useful traces.
- **Local-first.** No data leaves the host without explicit configuration.
- **Light on user code.** Decorators must work on sync and async functions, capture nothing sensitive by default.

## Decision

### Span name
- Span name = `func.__qualname__` (e.g. `ResearchAgent.gather_notes`).

### Span attributes (always)
| Attribute | Value | Source |
|---|---|---|
| `tentacle.kind` | `"agent"` \| `"tool"` \| `"human_review"` | tentacle (custom) |
| `tentacle.sdk.version` | `tentacle.__version__` | tentacle (custom) |
| `code.function` | `func.__qualname__` | OTel semconv |
| `code.namespace` | `func.__module__` | OTel semconv |

### Span attributes (LLM calls, captured by auto-instrumentation)
Use the upstream **OTel GenAI semantic conventions** verbatim — no rewrite, no aliasing:

| Attribute | Meaning |
|---|---|
| `gen_ai.system` | `"openai"` / `"anthropic"` / ... |
| `gen_ai.request.model` | model id (e.g. `gpt-4o-2024-08-06`) |
| `gen_ai.usage.input_tokens` | prompt tokens |
| `gen_ai.usage.output_tokens` | completion tokens |

Cost is **not** an SDK attribute. Backend joins these against `model_pricing` to produce `cost_usd`.

### NeedsHumanReview signal
When user code raises `tentacle.NeedsHumanReview` inside any decorated function:
- The current span gets `tentacle.needs_human_review = true`.
- A span event is recorded: name `"tentacle.needs_human_review"`, attributes `tentacle.review.prompt` (string) + `tentacle.review.payload` (JSON-encoded string, capped at 4 KB).
- Span status is set to `OK` (not `ERROR`) — this is a controlled pause, not a failure.
- The exception still propagates out of the wrapper unchanged.

### Span kind = OTel SpanKind
All tentacle spans use `SpanKind.INTERNAL`. The `tentacle.kind` attribute (above) carries our extra dimension.

### Argument / return capture
**Off by default.** In v0.1 we do not record function inputs or outputs. Users can opt in later via a flag — separate ADR when we add it. Rationale: silent secret capture is the worst kind of bug we could ship.

## Consequences

### Positive
- Standards-first: tracing data is consumable by any OTel backend.
- Backend cost computation is decoupled from the SDK release cycle.
- Pause-for-human is observable as both an attribute (queryable) and an event (rich payload).
- No accidental secret exfiltration in v0.1.

### Negative / accepted risks
- We diverge from OTel standard `SpanKind` semantics by adding `tentacle.kind`. Acceptable because OTel's `SpanKind` enum is rigid (server/client/etc.) and doesn't model the agent/tool distinction we need.
- The 4 KB cap on review payload truncates large structured prompts. Documented; users can pass a reference instead.

## Ripple plan

- [x] **Schema doc / fixtures** — this ADR + minimal/with-tokens fixtures in `tests/contract/`
- [x] **SDK** (`tentacle`) emits the new shape; version bump to `0.1.0`
- [ ] **Backend** ingestion + serving + migration → PR #4
- [ ] **Dashboard** types regenerated + UI consumes the new field → PR #6
- [ ] `scripts/e2e.sh` passes against the new shape → PR #4
- [x] `CLAUDE.md` §5 still matches (no flow change, just attribute names)

## Alternatives considered

- **Use OTel `SpanKind` for agent/tool.** Rejected — `SpanKind` is a fixed enum; adding values isn't allowed. `tentacle.kind` is the conventional way to layer in domain-specific kinds.
- **Custom KrakenOps wire format instead of OTLP.** Rejected at the architecture level (see CLAUDE.md §2 + the PR #1 question round). Standard wins on portability.
- **SDK computes cost.** Rejected — pricing changes faster than the SDK release cycle.
