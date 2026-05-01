"""Pricing seed + lookup."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import text

from app.db import engine
from app.db.pricing import load_effective_pricing, lookup_cost, seed_pricing


def test_default_pricing_seeded() -> None:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT model FROM model_pricing")).all()
    models = {r[0] for r in rows}
    # A few high-confidence anchors from default.yaml.
    assert "gpt-4o-2024-08-06" in models
    assert "claude-sonnet-4-6" in models


def test_lookup_cost_known_model() -> None:
    cost = lookup_cost(engine, "gpt-4o-2024-08-06", input_tokens=1000, output_tokens=1000)
    # 1k input @ $0.0025 + 1k output @ $0.0100 = $0.0125
    assert cost == 0.0125


def test_lookup_cost_unknown_model_returns_none() -> None:
    assert lookup_cost(engine, "totally-fake-model-xyz", 1000, 1000) is None


def test_user_override_replaces_default(tmp_path: Path, monkeypatch) -> None:
    # Build an override that replaces gpt-4o-2024-08-06 with cheaper imaginary pricing.
    override = tmp_path / "pricing.yaml"
    override.write_text(
        yaml.safe_dump(
            {
                "source_label": "test-override",
                "models": [
                    {
                        "model": "gpt-4o-2024-08-06",
                        "input_per_1k_usd": 0.0001,
                        "output_per_1k_usd": 0.0002,
                    }
                ],
            }
        )
    )
    merged = load_effective_pricing(override_path=override)
    assert merged["gpt-4o-2024-08-06"]["input_per_1k_usd"] == 0.0001
    assert merged["gpt-4o-2024-08-06"]["source"] == "test-override"
    # Non-overridden models still come from the default file.
    assert "claude-sonnet-4-6" in merged


def test_seed_is_idempotent(truncate_db: None) -> None:
    n1 = seed_pricing(engine)
    n2 = seed_pricing(engine)
    assert n1 == n2
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM model_pricing")).scalar_one()
    assert count == n1
