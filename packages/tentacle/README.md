# tentacle

Agent-agnostic OpenTelemetry decorators for [KrakenOps](https://github.com/eikekohlmeyer/KrakenOps).

> **Heads-up:** the PyPI distribution name is **`krakenops`**, but the Python
> module is **`tentacle`** (Pillow-style — see [ADR 0004](../../docs/adr/0004-pypi-distribution-name.md)
> for why). Install with `pip install krakenops`, import with `import tentacle`.
> The unrelated `tentacle` package on PyPI is **not** us.

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

**v0.0.1** — first public release. Real OTLP/HTTP export, sync and async decorators, `NeedsHumanReview` signal, optional OpenAI/Anthropic auto-instrumentation. Wire format described in [ADR 0001](../../docs/adr/0001-tentacle-span-schema.md); APIs and on-the-wire shapes may still shift before 1.0.0.

## Install

```sh
pip install krakenops                  # core only — no auto-instrumentation
pip install 'krakenops[openai]'        # + OpenAI v2 auto-instrumentation
pip install 'krakenops[anthropic]'     # + Anthropic auto-instrumentation
pip install 'krakenops[all]'           # everything
```

Then `import tentacle` (not `import krakenops`).

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

## Releasing

See [`../../docs/RELEASING.md`](../../docs/RELEASING.md). Pushing a `krakenops-v*` tag triggers `.github/workflows/release-krakenops.yml` which builds the wheel + sdist and publishes via OIDC trusted publishing — no API tokens stored. TestPyPI on every tag, real PyPI on stable tags.

## Design

See [`../../CLAUDE.md`](../../CLAUDE.md) §2.2 (overview) and §5.1 (data flow), [ADR 0001](../../docs/adr/0001-tentacle-span-schema.md) (span schema), and [ADR 0004](../../docs/adr/0004-pypi-distribution-name.md) (why the dist name and module name differ).
