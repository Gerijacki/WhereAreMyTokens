"""Aggregation helpers shared by the API routers."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Date, case, cast, func, literal_column
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from wamt.config import get_settings
from wamt.db import ApiCall

TOKEN_COLUMNS = ("input_tokens", "output_tokens", "cache_write_5m", "cache_write_1h", "cache_read")


def since(days: int | None) -> datetime | None:
    return datetime.now(UTC) - timedelta(days=days) if days else None


def day_bucket(db: Session, column) -> ColumnElement:
    """Calendar day of a timestamp in the configured timezone."""
    if db.bind.dialect.name == "postgresql":
        tz = get_settings().timezone.replace("'", "")
        return cast(func.timezone(literal_column(f"'{tz}'"), column), Date)
    return func.date(column)


def usage_columns() -> list[ColumnElement]:
    """SUM() of every token kind + cost, labeled for row mapping."""
    cols = [func.coalesce(func.sum(getattr(ApiCall, c)), 0).label(c) for c in TOKEN_COLUMNS]
    cols.append(func.coalesce(func.sum(ApiCall.cost_usd), 0.0).label("cost_usd"))
    cols.append(func.count(ApiCall.id).label("api_calls"))
    cols.append(func.sum(case((ApiCall.cost_usd.is_(None), 1), else_=0)).label("unpriced_calls"))
    return cols


def usage_dict(row) -> dict:
    d = {c: int(getattr(row, c) or 0) for c in TOKEN_COLUMNS}
    d["cache_write"] = d["cache_write_5m"] + d["cache_write_1h"]
    d["total_tokens"] = d["input_tokens"] + d["output_tokens"] + d["cache_write"] + d["cache_read"]
    prompt_side = d["input_tokens"] + d["cache_write"] + d["cache_read"]
    d["cache_hit_ratio"] = round(d["cache_read"] / prompt_side, 4) if prompt_side else None
    d["cost_usd"] = round(float(row.cost_usd or 0), 4)
    d["api_calls"] = int(row.api_calls or 0)
    d["unpriced_calls"] = int(getattr(row, "unpriced_calls", 0) or 0)
    return d
