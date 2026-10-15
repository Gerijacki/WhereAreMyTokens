"""Prometheus exposition at /metrics (hand-written text format, no client library needed)."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wamt.analytics.blocks import compute_limits
from wamt.collector.ingest import STATUS
from wamt.config import get_settings
from wamt.db import ApiCall, Insight, get_db

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]
KINDS = {"input": "input_tokens", "output": "output_tokens", "cache_write_5m": "cache_write_5m",
         "cache_write_1h": "cache_write_1h", "cache_read": "cache_read"}


def _label(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics(db: DB, authorization: Annotated[str | None, Header()] = None):
    token = get_settings().metrics_token
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Bearer token required")

    lines: list[str] = []

    def metric(name: str, mtype: str, help_: str, samples: list[tuple[dict, float]]) -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {mtype}")
        for labels, value in samples:
            lbl = ",".join(f'{k}="{_label(str(v))}"' for k, v in labels.items())
            lines.append(f"{name}{{{lbl}}} {value}" if lbl else f"{name} {value}")

    rows = db.execute(select(ApiCall.model, func.count(ApiCall.id), func.coalesce(func.sum(ApiCall.cost_usd), 0.0),
                             *[func.coalesce(func.sum(getattr(ApiCall, c)), 0) for c in KINDS.values()])
                      .group_by(ApiCall.model)).all()
    metric("wamt_api_calls_total", "counter", "Claude API calls seen in transcripts.",
           [({"model": r[0]}, r[1]) for r in rows])
    metric("wamt_cost_usd_total", "counter", "API-equivalent cost in USD.",
           [({"model": r[0]}, round(r[2], 6)) for r in rows])
    metric("wamt_tokens_total", "counter", "Tokens by model and kind.",
           [({"model": r[0], "kind": k}, r[3 + i]) for r in rows for i, k in enumerate(KINDS)])
    read = sum(r[7] for r in rows)
    prompt_side = sum(r[3] + r[5] + r[6] + r[7] for r in rows)
    metric("wamt_cache_hit_ratio", "gauge", "Cache reads / all prompt-side tokens.",
           [({}, round(read / prompt_side, 6) if prompt_side else 0)])

    lim = compute_limits(db, days=7)
    cur = lim["current"]
    metric("wamt_block_cost_usd", "gauge", "API-equivalent cost of the current 5-hour block.",
           [({}, cur["cost_usd"] if cur else 0)])
    metric("wamt_block_projected_cost_usd", "gauge", "Projected cost of the current 5-hour block.",
           [({}, cur["projected_cost_usd"] if cur else 0)])
    metric("wamt_block_burn_usd_per_hour", "gauge", "Burn rate in the current 5-hour block.",
           [({}, cur["burn_usd_per_hour"] if cur else 0)])

    ins = db.execute(select(Insight.severity, func.count(Insight.id), func.coalesce(func.sum(Insight.est_usd_month), 0.0))
                     .where(Insight.status == "open", Insight.stale.is_(False)).group_by(Insight.severity)).all()
    metric("wamt_insights_open", "gauge", "Open insights by severity.", [({"severity": r[0]}, r[1]) for r in ins])
    metric("wamt_insights_savings_usd_month", "gauge", "Estimated monthly savings of open insights.",
           [({}, round(sum(r[2] for r in ins), 4))])
    metric("wamt_ingest_last_scan_timestamp_seconds", "gauge", "Unix time of the last transcript scan.",
           [({}, STATUS.last_scan_at.timestamp() if STATUS.last_scan_at else 0)])
    return "\n".join(lines) + "\n"
