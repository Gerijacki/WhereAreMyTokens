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


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    usd_month: float


def _read(path: str | None) -> dict:
    file = Path(path) if path else (get_settings().pricing_file or BUNDLED)
    return yaml.safe_load(file.read_text(encoding="utf-8"))


@lru_cache
def load_prices(path: str | None = None) -> tuple[ModelPrice, ...]:
    data = _read(path)
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


@lru_cache
def load_plans(path: str | None = None) -> tuple[Plan, ...]:
    """Subscription plans, cheapest first. A custom pricing file without `plans` keeps the bundled ones."""
    plans = _read(path).get("plans") or yaml.safe_load(BUNDLED.read_text(encoding="utf-8"))["plans"]
    return tuple(sorted((Plan(id=str(p["id"]), name=str(p["name"]), usd_month=float(p["usd_month"]))
                         for p in plans), key=lambda p: p.usd_month))


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
