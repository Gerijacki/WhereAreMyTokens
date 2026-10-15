"""Detect prompt-cache rebuilds in a session's main thread.

In a healthy conversation every API call reads the previous context from cache and only
writes the new tail. A *rebuild* is a call that writes a large prefix again although the
previous call had it cached. That costs the cache-write price instead of the (much
cheaper) cache-read price for the whole context.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime

from wamt.pricing import price_for

MIN_REBUILD_TOKENS = 5_000
TTL_5M = 300
TTL_1H = 3600

CAUSES = {
    "idle_expired": "Idle longer than the cache TTL",
    "compaction": "Context compacted",
    "model_switch": "Model switched",
    "prefix_change": "Prompt prefix changed",
}


@dataclass
class Call:
    id: str
    ts: datetime
    model: str
    input_tokens: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h

    @property
    def context(self) -> int:
        return self.input_tokens + self.cache_write + self.cache_read


@dataclass
class Rebuild:
    call_id: str
    ts: datetime
    model: str
    cause: str
    tokens: int
    wasted_usd: float
    gap_seconds: float


def _wasted(call: Call) -> float:
    """Extra cost of writing the prefix versus reading it from cache."""
    p = price_for(call.model)
    if p is None:
        return 0.0
    return (call.cache_write_5m * (p.cache_write_5m - p.cache_read)
            + call.cache_write_1h * (p.cache_write_1h - p.cache_read)) / 1_000_000


def detect_rebuilds(calls: list[Call], compactions: list[datetime]) -> list[Rebuild]:
    calls = sorted(calls, key=lambda c: c.ts)
    out: list[Rebuild] = []
    for prev, cur in itertools.pairwise(calls):
        if cur.cache_write < MIN_REBUILD_TOKENS:
            continue
        if cur.cache_read >= 0.5 * prev.context:
            continue  # normal growth: most of the prefix came from cache
        gap = (cur.ts - prev.ts).total_seconds()
        ttl = TTL_1H if (prev.cache_write_1h or cur.cache_write_1h) else TTL_5M
        if any(prev.ts <= c <= cur.ts for c in compactions):
            cause = "compaction"
        elif cur.model != prev.model:
            cause = "model_switch"
        elif gap > ttl:
            cause = "idle_expired"
        else:
            cause = "prefix_change"
        out.append(Rebuild(call_id=cur.id, ts=cur.ts, model=cur.model, cause=cause,
                           tokens=cur.cache_write, wasted_usd=round(_wasted(cur), 6), gap_seconds=gap))
    return out
