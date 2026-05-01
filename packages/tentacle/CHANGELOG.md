# Changelog

All notable changes to the SDK. The PyPI distribution name is **`krakenops`**;
the Python module is **`tentacle`** (see [ADR 0004](../../docs/adr/0004-pypi-distribution-name.md)).

Versions before 1.0.0 are pre-stable: APIs may change between any two
0.0.x or 0.x.y releases. See SemVer §4.

## [0.0.1] — 2026-05-01

First public release. The internal v1.0 framing has been rolled back to
0.0.1 to better signal that the project is still finding its shape; the
APIs and wire format described in ADR 0001 are stable in spirit but not
contractually frozen until a future 1.0.0.

### Added
- `tentacle.init(endpoint=..., service_name=..., headers=..., enable_openai=True, enable_anthropic=True, resource_attributes=...)` — idempotent OTel pipeline setup.
- Decorators: `@tentacle.track_agent`, `@tentacle.tool`, `@tentacle.require_human`. Sync and async supported.
- `tentacle.NeedsHumanReview(prompt, payload=None)` exception.
- Optional auto-instrumentation extras: `krakenops[openai]`, `krakenops[anthropic]`, `krakenops[all]`.
- Wire format described in ADR 0001 (subject to change before 1.0.0).

### Distribution
- Published to PyPI as `krakenops`. Install with `pip install krakenops`,
  import with `import tentacle`. The `tentacle` PyPI name (an unrelated
  legacy package) is not affiliated with this project.
