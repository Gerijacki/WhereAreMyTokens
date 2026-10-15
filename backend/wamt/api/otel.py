"""OpenTelemetry (OTLP/HTTP JSON) receiver for Claude Code's native telemetry.

Point Claude Code at it with:
    CLAUDE_CODE_ENABLE_TELEMETRY=1  OTEL_METRICS_EXPORTER=otlp  OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_PROTOCOL=http/json  OTEL_EXPORTER_OTLP_ENDPOINT=http://<wamt>:8787
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <device token>"   # when auth is enabled

Kept: `claude_code.token.usage` / `claude_code.cost.usage` metric points and
`claude_code.api_request` events. Identity attributes (user.email, account/org ids) are
dropped on arrival. Only the JSON encoding is supported, so the protocol must be http/json.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wamt import devices
from wamt.api.queries import since
from wamt.auth import auth_required
from wamt.db import OtelPoint, get_db

router = APIRouter()
DB = Annotated[Session, Depends(get_db)]

METRICS = {"claude_code.token.usage", "claude_code.cost.usage"}
EVENTS = {"claude_code.api_request", "api_request"}
DROP_ATTRS = {"user.email", "user.account_uuid", "user.account_id", "organization.id", "user.id", "prompt",
              "prompt_text"}
KEEP_ATTRS = {"query_source", "speed", "effort", "terminal.type", "app.version", "agent.name", "skill.name",
              "duration_ms", "request_id"}


def _source(db: DB, authorization: Annotated[str | None, Header()] = None) -> str:
    device = devices.verify(db, devices.bearer(authorization))
    if device is not None:
        return device.name
    if auth_required():
        raise HTTPException(401, "Device token required", headers={"WWW-Authenticate": "Bearer"})
    return "otel"


def _value(v: dict):
    for k in ("stringValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    if "intValue" in v:
        return int(v["intValue"])  # OTLP JSON encodes int64 as a string
    return None


def _attrs(items: list | None) -> dict:
    return {a["key"]: _value(a.get("value") or {}) for a in items or [] if a.get("key") not in DROP_ATTRS}


def _ts(nanos) -> datetime:
    try:
        return datetime.fromtimestamp(int(nanos) / 1e9, tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def _json(request: Request) -> dict:
    if "json" not in request.headers.get("content-type", ""):
        raise HTTPException(415, "Only OTLP/HTTP JSON is supported: set OTEL_EXPORTER_OTLP_PROTOCOL=http/json")
    try:
        return json.loads(await request.body())
    except json.JSONDecodeError as e:
        raise HTTPException(400, "Invalid JSON") from e


@router.post("/v1/metrics")
async def otlp_metrics(request: Request, db: DB, source: Annotated[str, Depends(_source)]):
    body = await _json(request)
    n = 0
    for rm in body.get("resourceMetrics") or []:
        res = _attrs((rm.get("resource") or {}).get("attributes"))
        for sm in rm.get("scopeMetrics") or []:
            for m in sm.get("metrics") or []:
                if m.get("name") not in METRICS:
                    continue
                data = m.get("sum") or m.get("gauge") or {}
                for dp in data.get("dataPoints") or []:
                    a = {**res, **_attrs(dp.get("attributes"))}
                    db.add(OtelPoint(
                        ts=_ts(dp.get("timeUnixNano")), source=source, kind="metric", name=m["name"],
                        session_id=a.get("session.id"), model=a.get("model"), type=a.get("type"),
                        value=_num(dp.get("asDouble", dp.get("asInt"))),
                        attrs=json.dumps({k: v for k, v in a.items() if k in KEEP_ATTRS}),
                    ))
                    n += 1
    db.commit()
    return {"partialSuccess": {}, "accepted": n}


@router.post("/v1/logs")
async def otlp_logs(request: Request, db: DB, source: Annotated[str, Depends(_source)]):
    body = await _json(request)
    n = 0
    for rl in body.get("resourceLogs") or []:
        res = _attrs((rl.get("resource") or {}).get("attributes"))
        for sl in rl.get("scopeLogs") or []:
            for rec in sl.get("logRecords") or []:
                a = {**res, **_attrs(rec.get("attributes"))}
                name = a.get("event.name") or _value(rec.get("body") or {})
                if name not in EVENTS:
                    continue
                db.add(OtelPoint(
                    ts=_ts(rec.get("timeUnixNano") or rec.get("observedTimeUnixNano")), source=source,
                    kind="event", name="claude_code.api_request", session_id=a.get("session.id"),
                    model=a.get("model"), value=_num(a.get("cost_usd")),
                    input_tokens=int(_num(a.get("input_tokens"))), output_tokens=int(_num(a.get("output_tokens"))),
                    cache_read=int(_num(a.get("cache_read_tokens"))),
                    cache_write=int(_num(a.get("cache_creation_tokens"))),
                    attrs=json.dumps({k: v for k, v in a.items() if k in KEEP_ATTRS}),
                ))
                n += 1
    db.commit()
    return {"partialSuccess": {}, "accepted": n}


@router.get("/api/telemetry")
def telemetry(db: DB, days: int = Query(30, ge=0, le=3650)):
    """Summary of `api_request` events received over OpenTelemetry (a second, push-based source)."""
    stmt = select(OtelPoint.source, OtelPoint.model, func.count(OtelPoint.id).label("requests"),
                  func.sum(OtelPoint.value).label("cost"), func.sum(OtelPoint.input_tokens).label("inp"),
                  func.sum(OtelPoint.output_tokens).label("out"), func.sum(OtelPoint.cache_read).label("cr"),
                  func.sum(OtelPoint.cache_write).label("cw"), func.max(OtelPoint.ts).label("last")
                  ).where(OtelPoint.kind == "event")
    start = since(days)
    if start is not None:
        stmt = stmt.where(OtelPoint.ts >= start)
    rows = db.execute(stmt.group_by(OtelPoint.source, OtelPoint.model)).all()
    last = max((r.last for r in rows), default=None)
    return {
        "active": bool(rows),
        "last_event_at": last,
        "live": bool(last and (last if last.tzinfo else last.replace(tzinfo=UTC)) > datetime.now(UTC) - timedelta(minutes=10)),
        "by_source_model": [
            {"source": r.source, "model": r.model, "requests": r.requests, "cost_usd": round(r.cost or 0, 4),
             "input_tokens": int(r.inp or 0), "output_tokens": int(r.out or 0), "cache_read": int(r.cr or 0),
             "cache_write": int(r.cw or 0)} for r in rows
        ],
    }
