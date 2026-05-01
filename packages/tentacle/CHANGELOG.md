# Changelog

All notable changes to the SDK. The PyPI distribution name is **`krakenops`**;
the Python module is **`tentacle`** (see [ADR 0004](../../docs/adr/0004-pypi-distribution-name.md)).

## [1.0.0] — 2026-05-01

First PyPI release.

### Added
- `tentacle.init(endpoint=..., service_name=..., headers=..., enable_openai=True, enable_anthropic=True, resource_attributes=...)` — idempotent OTel pipeline setup.
- Decorators: `@tentacle.track_agent`, `@tentacle.tool`, `@tentacle.require_human`. Sync and async supported.
- `tentacle.NeedsHumanReview(prompt, payload=None)` exception.
- Optional auto-instrumentation extras: `krakenops[openai]`, `krakenops[anthropic]`, `krakenops[all]`.
- Wire format pinned by ADR 0001.

### Distribution
- Published to PyPI as `krakenops`. Install with `pip install krakenops`,
  import with `import tentacle`. The `tentacle` PyPI name (an unrelated
  legacy package) is not affiliated with this project.
