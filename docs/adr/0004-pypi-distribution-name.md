# ADR 0004: PyPI distribution name is `krakenops`; Python module stays `tentacle`

- **Status:** Accepted
- **Date:** 2026-05-01
- **Deciders:** @eikekohlmeyer
- **Affects:** sdk · packaging

## Context

PR #9 ships the first PyPI release of the SDK. The internal/Python name has
been **`tentacle`** since PR #1 — the cephalopod-tentacle metaphor of the
KrakenOps project, decorators all spelled `@tentacle.track_agent` etc. Span
attributes use a `tentacle.*` namespace. ADR 0001 codifies this.

The PyPI name `tentacle` is **already taken** (an unrelated 2014-vintage
package). We can't publish under that name.

## Decision

Adopt the **Pillow / PIL pattern**:

- **PyPI distribution name:** `krakenops`
- **Python module:** stays `tentacle`

So users do:

```sh
pip install krakenops
```

```python
import tentacle
```

Nothing else changes:

- Public API: `tentacle.init`, `@tentacle.track_agent`, `@tentacle.tool`,
  `@tentacle.require_human`, `tentacle.NeedsHumanReview` — unchanged.
- Span attribute namespace: `tentacle.kind`, `tentacle.sdk.version`,
  `tentacle.needs_human_review` — unchanged.
- Span event name: `tentacle.needs_human_review` — unchanged.
- Env var: `TENTACLE_ENDPOINT` — unchanged.
- Directory: `packages/tentacle/` — unchanged.
- Backend ingest, contract fixtures, dashboard types — unchanged.

The change is concentrated in two places:

1. `packages/tentacle/pyproject.toml` — `name = "tentacle"` →
   `name = "krakenops"`. The Hatch `[tool.hatch.build.targets.wheel].packages`
   stays `["src/tentacle"]` so the wheel installs the `tentacle` Python
   module.
2. The `/release-tentacle` skill is renamed to `/release-krakenops` and its
   instructions reference `pip install krakenops` for verification.

## Consequences

### Positive
- **Zero churn** in code, contracts, fixtures, tests, ADR 0001, CLAUDE.md.
- v1.0 ships now. The `pip install` ↔ `import` mismatch is well-precedented
  (Pillow, Beautiful Soup → `bs4`, OpenCV → `cv2`).
- Brand stays differentiated: KrakenOps the product / `tentacle` the SDK.

### Negative / accepted risks
- **Discoverability friction.** A user who `import tentacle` in code might
  Google "pip install tentacle" and get the wrong package. Mitigations:
  - README opens with the install line in code-block form.
  - The PyPI project description leads with the disambiguation.
  - The wheel ships with a top-level docstring noting the distribution name.
- A future major rev might revisit this if the `tentacle` PyPI name
  becomes available (unlikely without PEP 541 takeover).

## Ripple plan

- [x] **SDK** — pyproject `name` only; bump to 1.0.0.
- [x] **Skill** — `/release-tentacle` renamed to `/release-krakenops`.
- [x] **README** — `pip install krakenops` everywhere; one disambiguation
      paragraph in the SDK README.
- [ ] **Backend / Dashboard / SDK code / fixtures / ADR 0001** — no change.

## Alternatives considered

- **Full rename to `krakenops` everywhere.** Rejected by the user: too much
  churn for too little benefit when nothing has shipped publicly. (Earlier
  draft of this ADR is preserved in git history.)
- **Negotiate the PyPI `tentacle` name via PEP 541.** Slow, uncertain.
  Doesn't fit the v1.0 timeline.
- **Different distribution name entirely (`kraken-sdk`, `tentacle-sdk`).**
  Adds a third brand. `krakenops` matches the project name, which is the
  least-confusing option among the available ones.
