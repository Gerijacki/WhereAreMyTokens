"""API-equivalent cost calculation from a YAML price table."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from wamt.config import get_settings

BUNDLED = Path(__file__).with_name("pricing.yaml")
PER_TOKEN = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    pattern: re.Pattern
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


@lru_cache
def load_prices(path: str | None = None) -> tuple[ModelPrice, ...]:
    file = Path(path) if path else (get_settings().pricing_file or BUNDLED)
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    prices = []
    for m in data["models"]:
        inp = float(m["input"])
        prices.append(
            ModelPrice(
                pattern=re.compile(m["match"]),
                input=inp,
                output=float(m["output"]),
                cache_write_5m=float(m.get("cache_write_5m", inp * 1.25)),
                cache_write_1h=float(m.get("cache_write_1h", inp * 2)),
                cache_read=float(m.get("cache_read", inp * 0.1)),
            )
        )
    return tuple(prices)


def price_for(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    for p in load_prices():
        if p.pattern.search(model):
            return p
    return None


def cost_breakdown(model: str | None, usage) -> dict[str, float]:
    """Split the cost of aggregated usage (anything with the token attributes) by token kind."""
    p = price_for(model)
    if p is None:
        return {}
    return {
        "input": usage.input_tokens * p.input / PER_TOKEN,
        "output": usage.output_tokens * p.output / PER_TOKEN,
        "cache_write": (usage.cache_write_5m * p.cache_write_5m + usage.cache_write_1h * p.cache_write_1h)
        / PER_TOKEN,
        "cache_read": usage.cache_read * p.cache_read / PER_TOKEN,
    }


def cost_usd(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_write_5m: int,
    cache_write_1h: int,
    cache_read: int,
) -> float | None:
    """Return the API-equivalent cost in USD, or None when the model is unpriced."""
    p = price_for(model)
    if p is None:
        return None
    return (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_write_5m * p.cache_write_5m
        + cache_write_1h * p.cache_write_1h
        + cache_read * p.cache_read
    ) / PER_TOKEN
