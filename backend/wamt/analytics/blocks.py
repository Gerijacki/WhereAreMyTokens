"""5-hour usage blocks, burn rate, weekday x hour heatmap and weekly totals."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt.api.queries import since
from wamt.config import get_settings
from wamt.db import ApiCall, ChatSession

BLOCK_HOURS = 5


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _scope(stmt, days: int, project_id: int | None):
    start = since(days)
    if start is not None:
        stmt = stmt.where(ApiCall.ts >= start)
    if project_id is not None:
        stmt = stmt.join(ChatSession, ChatSession.id == ApiCall.session_id).where(ChatSession.project_id == project_id)
    return stmt


def compute_limits(db: Session, days: int = 30, project_id: int | None = None) -> dict:
    """5-hour usage blocks (approximation of subscription windows), burn rate and a weekday x hour heatmap.

    A block starts at the hour of the first request after the previous block ended and lasts
    5 hours, the convention used by community tools. Anthropic doesn't publish the exact limits,
    so blocks are compared with your own history rather than a quota.
    """
    tz = ZoneInfo(get_settings().timezone)
    total_tokens = ApiCall.input_tokens + ApiCall.output_tokens + ApiCall.cache_write_5m + ApiCall.cache_write_1h
    rows = db.execute(_scope(
        select(ApiCall.ts, ApiCall.cost_usd, total_tokens.label("tokens"), ApiCall.cache_read, ApiCall.output_tokens)
        .order_by(ApiCall.ts), days, project_id)).all()

    blocks: list[dict] = []
    heat = [[0.0] * 24 for _ in range(7)]
    weekly: dict[str, float] = defaultdict(float)
    for r in rows:
        ts = _aware(r.ts)
        cost = r.cost_usd or 0.0
        local = ts.astimezone(tz)
        heat[local.weekday()][local.hour] += cost
        week_start = (local - timedelta(days=local.weekday())).date().isoformat()
        weekly[week_start] += cost
        if not blocks or ts >= blocks[-1]["end"]:
            start = ts.replace(minute=0, second=0, microsecond=0)
            blocks.append({"start": start, "end": start + timedelta(hours=BLOCK_HOURS), "first": ts, "last": ts,
                           "cost_usd": 0.0, "tokens": 0, "cache_read": 0, "output_tokens": 0, "calls": 0})
        b = blocks[-1]
        b["last"] = ts
        b["cost_usd"] += cost
        b["tokens"] += int(r.tokens or 0)
        b["cache_read"] += int(r.cache_read or 0)
        b["output_tokens"] += int(r.output_tokens or 0)
        b["calls"] += 1

    now = datetime.now(UTC)
    current = None
    if blocks and blocks[-1]["end"] > now:
        b = blocks[-1]
        elapsed_h = max((now - b["first"]).total_seconds() / 3600, 1 / 60)
        rate = b["cost_usd"] / elapsed_h
        remaining_h = (b["end"] - now).total_seconds() / 3600
        current = {"start": b["start"], "end": b["end"], "cost_usd": round(b["cost_usd"], 4), "tokens": b["tokens"],
                   "calls": b["calls"], "burn_usd_per_hour": round(rate, 4),
                   "projected_cost_usd": round(b["cost_usd"] + rate * remaining_h, 4),
                   "minutes_left": int(remaining_h * 60)}
    past = [b for b in blocks if b["end"] <= now] or blocks
    peak = max((b["cost_usd"] for b in past), default=0.0)
    return {
        "block_hours": BLOCK_HOURS,
        "timezone": str(tz),
        "current": current,
        "peak_block_cost_usd": round(peak, 4),
        "median_block_cost_usd": round(sorted(b["cost_usd"] for b in past)[len(past) // 2], 4) if past else 0.0,
        "blocks": [{"start": b["start"], "end": b["end"], "cost_usd": round(b["cost_usd"], 4), "tokens": b["tokens"],
                    "cache_read": b["cache_read"], "output_tokens": b["output_tokens"], "calls": b["calls"],
                    "active_minutes": int((b["last"] - b["first"]).total_seconds() / 60)} for b in blocks],
        "heatmap": [[round(v, 4) for v in row] for row in heat],  # [weekday Mon=0][hour]
        "weekly": [{"week": k, "cost_usd": round(v, 4)} for k, v in sorted(weekly.items())],
    }
