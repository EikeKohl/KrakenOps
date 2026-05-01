"""Load + seed model pricing.

Default file ships with the package (apps/backend/pricing/default.yaml). User
overrides at ~/.krakenops/pricing.yaml replace the matching `model` key. Both
files share the same shape (see the default for documentation).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import PRICING_DEFAULT_PATH, PRICING_OVERRIDE_PATH

_log = logging.getLogger("krakenops.pricing")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _flatten(doc: dict[str, Any], default_source: str) -> dict[str, dict[str, Any]]:
    """Return {model: {input_per_1k_usd, output_per_1k_usd, source}}."""
    label = str(doc.get("source_label") or default_source)
    out: dict[str, dict[str, Any]] = {}
    for entry in doc.get("models") or []:
        model = entry["model"]
        out[model] = {
            "input_per_1k_usd": float(entry["input_per_1k_usd"]),
            "output_per_1k_usd": float(entry["output_per_1k_usd"]),
            "source": str(entry.get("source") or label),
        }
    return out


def load_effective_pricing(
    default_path: Path | None = None,
    override_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    default_path = default_path or PRICING_DEFAULT_PATH
    override_path = override_path or PRICING_OVERRIDE_PATH

    base = _flatten(_load_yaml(default_path), default_source="default")
    user = _flatten(_load_yaml(override_path), default_source="user-override")

    merged = {**base, **user}  # user wins on collisions
    return merged


def seed_pricing(engine: Engine) -> int:
    """UPSERT current pricing into the model_pricing table. Returns row count written."""
    pricing = load_effective_pricing()
    if not pricing:
        _log.warning("no pricing entries found; cost_usd will always be NULL")
        return 0

    now = int(time.time())
    rows = [
        {
            "model": model,
            "input_per_1k_usd": vals["input_per_1k_usd"],
            "output_per_1k_usd": vals["output_per_1k_usd"],
            "source": vals["source"],
            "updated_at_s": now,
        }
        for model, vals in pricing.items()
    ]

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO model_pricing"
                " (model, input_per_1k_usd, output_per_1k_usd, source, updated_at_s)"
                " VALUES (:model, :input_per_1k_usd, :output_per_1k_usd, :source, :updated_at_s)"
                " ON CONFLICT(model) DO UPDATE SET"
                " input_per_1k_usd = excluded.input_per_1k_usd,"
                " output_per_1k_usd = excluded.output_per_1k_usd,"
                " source = excluded.source,"
                " updated_at_s = excluded.updated_at_s"
            ),
            rows,
        )

    _log.info("seeded %d pricing rows", len(rows))
    return len(rows)


def lookup_cost(
    engine: Engine, model: str, input_tokens: int, output_tokens: int
) -> float | None:
    """Return cost in USD for a given LLM call. None if model isn't priced."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT input_per_1k_usd, output_per_1k_usd"
                " FROM model_pricing WHERE model = :m"
            ),
            {"m": model},
        ).first()
    if row is None:
        return None
    in_rate, out_rate = row
    return round((input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate, 8)
