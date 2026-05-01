# tentacle

Agent-agnostic OpenTelemetry decorators for [KrakenOps](https://github.com/eikekohlmeyer/KrakenOps).

```python
import tentacle

tentacle.init(endpoint="http://localhost:8787/v1/traces")

@tentacle.track_agent
def my_agent(topic: str) -> str:
    return summarize(gather(topic))

@tentacle.tool
def gather(topic: str) -> list[str]: ...

@tentacle.require_human
def summarize(notes: list[str]) -> str:
    if ambiguous(notes):
        raise tentacle.NeedsHumanReview("pick a source", payload={"options": [...]})
    ...
```

## Status

**v0.1.0** — first real release. Real OTLP/HTTP export, sync and async decorators, `NeedsHumanReview` signal, optional OpenAI/Anthropic auto-instrumentation. Span schema is locked by [ADR 0001](../../docs/adr/0001-tentacle-span-schema.md).

## Install

```sh
pip install tentacle                  # core only — no auto-instrumentation
pip install 'tentacle[openai]'        # + OpenAI v2 auto-instrumentation
pip install 'tentacle[anthropic]'     # + Anthropic auto-instrumentation
pip install 'tentacle[all]'           # everything
```

## Usage

`tentacle.init()` is **idempotent** — call it once at the entry point of your script. If you forget, decorators still work; spans just go to OTel's default no-op tracer.

| Function | Purpose |
|---|---|
| `tentacle.init(endpoint=..., service_name=..., enable_openai=True, ...)` | Configure the OTLP/HTTP exporter. Reads `TENTACLE_ENDPOINT` from env if `endpoint` is omitted. |
| `@tentacle.track_agent` | Mark an agent entry point. Span carries `tentacle.kind = "agent"`. |
| `@tentacle.tool` | Mark a tool call. Span carries `tentacle.kind = "tool"`. |
| `@tentacle.require_human` | Mark a function that may pause for human input. Span carries `tentacle.kind = "human_review"`. |
| `tentacle.NeedsHumanReview(prompt, payload=None)` | Raise inside any decorated function to pause; backend flips the GH ticket to "Needs Human Review". |

**Sync and async are both supported** — the decorators detect coroutine functions automatically.

## What's captured

By default, **only span shape and structure**. No function arguments, no return values, no environment variables. Token usage and model names are captured automatically from `openai`/`anthropic` SDK calls when the corresponding extra is installed. Cost is computed in the backend (not the SDK) so pricing changes don't require a release. See ADR 0001.

## Develop

```sh
uv sync
uv run pytest
uv run ruff check .
```

Tests use `opentelemetry.sdk.trace.export.InMemorySpanExporter` — no network I/O.

## Design

See [`../../CLAUDE.md`](../../CLAUDE.md) §2.2 (overview) and §5.1 (data flow), and [ADR 0001](../../docs/adr/0001-tentacle-span-schema.md) (span schema).
