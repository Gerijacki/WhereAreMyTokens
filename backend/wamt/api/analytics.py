"""M2/M3 endpoints: categories, tools, cache, usage blocks, insights."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from wamt.analytics.blocks import compute_limits
from wamt.analytics.cache import CAUSES
from wamt.analytics.classify import category_names, load_rules
from wamt.analytics.commands import SHELL_TOOLS
from wamt.api.queries import day_bucket, since, usage_columns, usage_dict
from wamt.db import ApiCall, ChatSession, Insight, Project, SessionEvent, ToolCall, Turn, get_db, get_meta
from wamt.pricing import price_for

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]
Days = Query(30, ge=0, le=3650, description="Look-back window in days; 0 = all time")
BLOCK_HOURS = 5


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _scope(stmt, ts_col, days: int, project_id: int | None, session_col=None):
    start = since(days)
    if start is not None:
        stmt = stmt.where(ts_col >= start)
    if project_id is not None:
        stmt = stmt.join(ChatSession, ChatSession.id == session_col).where(ChatSession.project_id == project_id)
    return stmt


# --------------------------------------------------------------------------- categories

@router.get("/categories")
def categories(db: DB, days: int = Days, project_id: int | None = None):
    cat = func.coalesce(Turn.category, "uncategorized").label("category")
    base = select(cat, *usage_columns()).join(Turn, Turn.id == ApiCall.turn_id)
    rows = db.execute(_scope(base, ApiCall.ts, days, project_id, ApiCall.session_id).group_by(cat)).all()

    turn_counts = dict(db.execute(
        _scope(select(cat, func.count(Turn.id)), Turn.ts, days, project_id, Turn.session_id).group_by(cat)).all())

    day = day_bucket(db, ApiCall.ts).label("day")
    daily = db.execute(_scope(
        select(day, cat, func.coalesce(func.sum(ApiCall.cost_usd), 0.0).label("cost_usd"))
        .join(Turn, Turn.id == ApiCall.turn_id), ApiCall.ts, days, project_id, ApiCall.session_id)
        .group_by(day, cat).order_by(day)).all()

    by_cat = []
    for r in rows:
        u = usage_dict(r)
        n = turn_counts.get(r.category, 0)
        by_cat.append({"category": r.category, "prompts": n, "cost_per_prompt": round(u["cost_usd"] / n, 4) if n else 0,
                       **u})
    by_cat.sort(key=lambda r: -r["cost_usd"])
    return {
        "categories": category_names(),
        "by_category": by_cat,
        "daily": [{"day": str(r.day), "category": r.category, "cost_usd": round(float(r.cost_usd), 4)} for r in daily],
    }


class CategoryUpdate(BaseModel):
    category: str | None  # None = back to the rule-based category


@router.patch("/turns/{turn_id}")
def set_turn_category(turn_id: str, body: CategoryUpdate, db: DB):
    t = db.get(Turn, turn_id)
    if t is None:
        raise HTTPException(404, "Turn not found")
    if body.category is None:
        t.category_source = None
        db.flush()
        from wamt.analytics.enrich import classify_turns

        classify_turns(db, turn_ids={turn_id})
    else:
        if body.category not in category_names():
            raise HTTPException(422, f"Unknown category. Use one of: {', '.join(category_names())}")
        t.category, t.category_source, t.category_confidence = body.category, "manual", 1.0
    db.commit()
    return {"id": t.id, "category": t.category, "category_source": t.category_source}


@router.post("/admin/reclassify")
def reclassify():
    from wamt.analytics.enrich import backfill

    load_rules.cache_clear()
    backfill(force=True)
    return {"ok": True}


# --------------------------------------------------------------------------- tools

@router.get("/tools")
def tools(db: DB, days: int = Days, project_id: int | None = None):
    def scoped(stmt):
        return _scope(stmt, ToolCall.ts, days, project_id, ToolCall.session_id)

    errors = func.sum(case((ToolCall.is_error, 1), else_=0))
    result_chars = func.coalesce(func.sum(ToolCall.result_chars), 0)
    by_tool = db.execute(scoped(
        select(ToolCall.name, func.count(ToolCall.id).label("calls"), errors.label("errors"),
               result_chars.label("chars"), func.count(func.distinct(ToolCall.session_id)).label("sessions"))
    ).group_by(ToolCall.name).order_by(desc("calls"))).all()

    commands = db.execute(scoped(
        select(ToolCall.signature, func.count(ToolCall.id).label("calls"), errors.label("errors"),
               result_chars.label("chars"), func.count(func.distinct(ToolCall.turn_id)).label("prompts"))
        .where(ToolCall.name.in_(SHELL_TOOLS), ToolCall.signature.is_not(None))
    ).group_by(ToolCall.signature).order_by(desc("calls")).limit(25)).all()

    files = db.execute(scoped(
        select(ToolCall.signature, func.count(ToolCall.id).label("calls"), result_chars.label("chars"),
               func.count(func.distinct(ToolCall.session_id)).label("sessions"))
        .where(ToolCall.name == "Read", ToolCall.signature.is_not(None))
    ).group_by(ToolCall.signature).order_by(desc("calls")).limit(25)).all()

    biggest = db.execute(scoped(
        select(ToolCall.id, ToolCall.name, ToolCall.signature, ToolCall.result_chars, ToolCall.session_id,
               ToolCall.turn_id, ToolCall.ts)
    ).order_by(desc(ToolCall.result_chars)).limit(15)).all()

    def tok(chars) -> int:
        return int(chars or 0) // 4

    return {
        "by_tool": [{"name": r.name, "calls": r.calls, "errors": int(r.errors or 0),
                     "error_rate": round((r.errors or 0) / r.calls, 4) if r.calls else 0,
                     "result_tokens": tok(r.chars), "avg_result_tokens": tok(r.chars) // max(r.calls, 1),
                     "sessions": r.sessions} for r in by_tool],
        "commands": [{"signature": r.signature, "calls": r.calls, "errors": int(r.errors or 0), "prompts": r.prompts,
                      "avg_result_tokens": tok(r.chars) // max(r.calls, 1)} for r in commands],
        "files": [{"path": r.signature, "reads": r.calls, "sessions": r.sessions,
                   "avg_result_tokens": tok(r.chars) // max(r.calls, 1)} for r in files],
        "biggest_results": [{"id": r.id, "name": r.name, "target": r.signature, "result_tokens": tok(r.result_chars),
                             "session_id": r.session_id, "turn_id": r.turn_id, "ts": r.ts} for r in biggest],
    }


# --------------------------------------------------------------------------- cache

@router.get("/cache")
def cache(db: DB, days: int = Days, project_id: int | None = None):
    by_model = db.execute(_scope(select(ApiCall.model, *usage_columns()), ApiCall.ts, days, project_id,
                                 ApiCall.session_id).group_by(ApiCall.model)).all()
    totals = {"cache_read": 0, "cache_write": 0, "input_tokens": 0, "saved_usd": 0.0, "read_usd": 0.0,
              "write_usd": 0.0}
    for r in by_model:
        p = price_for(r.model)
        totals["cache_read"] += r.cache_read
        totals["cache_write"] += r.cache_write_5m + r.cache_write_1h
        totals["input_tokens"] += r.input_tokens
        if p:
            read = r.cache_read * p.cache_read / 1e6
            write = (r.cache_write_5m * p.cache_write_5m + r.cache_write_1h * p.cache_write_1h) / 1e6
            uncached = (r.cache_read + r.cache_write_5m + r.cache_write_1h) * p.input / 1e6
            totals["read_usd"] += read
            totals["write_usd"] += write
            totals["saved_usd"] += uncached - read - write
    prompt_side = totals["cache_read"] + totals["cache_write"] + totals["input_tokens"]
    totals["hit_ratio"] = round(totals["cache_read"] / prompt_side, 4) if prompt_side else None

    ev = _scope(select(SessionEvent), SessionEvent.ts, days, project_id, SessionEvent.session_id)
    events = db.scalars(ev.where(SessionEvent.kind == "cache_rebuild").order_by(desc(SessionEvent.ts))).all()
    by_cause: dict[str, dict] = {}
    per_session: dict[str, dict] = defaultdict(lambda: {"rebuilds": 0, "tokens": 0, "wasted_usd": 0.0})
    for e in events:
        c = by_cause.setdefault(e.cause, {"cause": e.cause, "label": CAUSES.get(e.cause, e.cause), "rebuilds": 0,
                                          "tokens": 0, "wasted_usd": 0.0})
        c["rebuilds"] += 1
        c["tokens"] += e.tokens
        c["wasted_usd"] += e.wasted_usd
        s = per_session[e.session_id]
        s["rebuilds"] += 1
        s["tokens"] += e.tokens
        s["wasted_usd"] += e.wasted_usd

    # Context size per call (main thread): what every call re-reads.
    ctx = (ApiCall.input_tokens + ApiCall.cache_write_5m + ApiCall.cache_write_1h + ApiCall.cache_read)
    contexts = db.execute(_scope(
        select(ApiCall.session_id, func.avg(ctx).label("avg"), func.max(ctx).label("max"),
               func.count(ApiCall.id).label("calls"))
        .where(ApiCall.is_sidechain.is_(False)), ApiCall.ts, days, project_id, ApiCall.session_id)
        .group_by(ApiCall.session_id).order_by(desc("avg")).limit(15)).all()
    titles = {s.id: s.title for s in db.scalars(select(ChatSession).where(
        ChatSession.id.in_({e.session_id for e in events} | {c.session_id for c in contexts})))}

    return {
        "totals": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in totals.items()},
        "by_cause": sorted(({**c, "wasted_usd": round(c["wasted_usd"], 4)} for c in by_cause.values()),
                           key=lambda c: -c["wasted_usd"]),
        "sessions": sorted(({"session_id": sid, "title": titles.get(sid), **v, "wasted_usd": round(v["wasted_usd"], 4)}
                            for sid, v in per_session.items()), key=lambda s: -s["wasted_usd"])[:15],
        "events": [{"session_id": e.session_id, "title": titles.get(e.session_id), "ts": e.ts, "cause": e.cause,
                    "model": e.model, "tokens": e.tokens, "wasted_usd": round(e.wasted_usd, 4),
                    "gap_seconds": e.gap_seconds} for e in events[:30]],
        "contexts": [{"session_id": c.session_id, "title": titles.get(c.session_id), "avg_context": int(c.avg or 0),
                      "max_context": int(c.max or 0), "calls": c.calls} for c in contexts],
    }


# --------------------------------------------------------------------------- usage blocks

@router.get("/limits")
def limits(db: DB, days: int = Query(30, ge=1, le=365), project_id: int | None = None):
    """5-hour usage blocks (approximation of subscription windows), burn rate and a weekday x hour heatmap."""
    return compute_limits(db, days, project_id)


# --------------------------------------------------------------------------- insights

def _insight_out(i: Insight, projects: dict[int, str]) -> dict:
    return {
        "id": i.id, "type": i.type, "title": i.title, "summary": i.summary, "severity": i.severity,
        "project_id": i.project_id, "project": projects.get(i.project_id) if i.project_id else None,
        "occurrences": i.occurrences, "est_tokens": i.est_tokens, "est_usd": i.est_usd,
        "est_usd_month": i.est_usd_month, "evidence": json.loads(i.evidence or "[]"),
        "artifact": ({"kind": i.artifact_kind, "path": i.artifact_path, "content": i.artifact_content}
                     if i.artifact_content else None),
        "status": i.status, "stale": i.stale, "first_seen": i.first_seen, "updated_at": i.updated_at,
    }


@router.get("/insights")
def insights(db: DB, status: str = Query("open", pattern="^(open|dismissed|done|all)$"),
             project_id: int | None = None, include_stale: bool = False):
    stmt = select(Insight)
    if status != "all":
        stmt = stmt.where(Insight.status == status)
    if not include_stale:
        stmt = stmt.where(Insight.stale.is_(False))
    if project_id is not None:
        stmt = stmt.where(Insight.project_id == project_id)
    rows = db.scalars(stmt).all()
    sev = {"high": 0, "medium": 1, "low": 2}
    rows = sorted(rows, key=lambda i: (sev.get(i.severity, 3), -i.est_usd_month))
    projects = dict(db.execute(select(Project.id, Project.name)).all())
    active = db.scalars(select(Insight).where(Insight.stale.is_(False))).all()
    return {
        "refreshed_at": get_meta(db, "insights_refreshed_at"),
        "summary": {
            "open": sum(1 for i in active if i.status == "open"),
            "done": sum(1 for i in active if i.status == "done"),
            "dismissed": sum(1 for i in active if i.status == "dismissed"),
            "open_usd_month": round(sum(i.est_usd_month for i in active if i.status == "open"), 2),
        },
        "items": [_insight_out(i, projects) for i in rows],
    }


class InsightUpdate(BaseModel):
    status: str


@router.patch("/insights/{insight_id}")
def update_insight(insight_id: str, body: InsightUpdate, db: DB):
    if body.status not in ("open", "dismissed", "done"):
        raise HTTPException(422, "status must be open, dismissed or done")
    i = db.get(Insight, insight_id)
    if i is None:
        raise HTTPException(404, "Insight not found")
    i.status = body.status
    db.commit()
    return {"id": i.id, "status": i.status}


@router.post("/insights/refresh")
def refresh_insights():
    from wamt.insights.engine import refresh

    return {"findings": refresh()}
