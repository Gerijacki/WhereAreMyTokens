import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from wamt.api.queries import day_bucket, scope, since, usage_columns, usage_dict
from wamt.collector.ingest import STATUS
from wamt.db import ApiCall, ChatSession, Project, SessionEvent, ToolCall, Turn, get_db
from wamt.pricing import cost_breakdown

router = APIRouter(prefix="/api")
DB = Annotated[Session, Depends(get_db)]

Days = Query(30, ge=0, le=3650, description="Look-back window in days; 0 = all time")


Device = Query(None, description="Only sessions from this device (`wamt agent` name, or the local source)")


def _filters(stmt, days: int, project_id: int | None, device: str | None = None):
    start = since(days)
    if start is not None:
        stmt = stmt.where(ApiCall.ts >= start)
    return scope(stmt, project_id, device, ApiCall.session_id)


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/ingest/status")
def ingest_status():
    s = STATUS
    return {
        "running": s.running,
        "files_seen": s.files_seen,
        "files_changed": s.files_changed,
        "lines_total": s.lines_total,
        "last_scan_at": s.last_scan_at,
        "last_scan_seconds": s.last_scan_seconds,
        "last_error": s.last_error,
    }


@router.get("/overview")
def overview(db: DB, days: int = Days, project_id: int | None = None, device: str | None = Device):
    totals = db.execute(_filters(select(*usage_columns()), days, project_id, device)).one()

    by_model = db.execute(
        _filters(select(ApiCall.model, *usage_columns()), days, project_id, device)
        .group_by(ApiCall.model).order_by(desc("cost_usd"))
    ).all()

    day = day_bucket(db, ApiCall.ts).label("day")
    daily = db.execute(
        _filters(select(day, *usage_columns()), days, project_id, device).group_by(day).order_by(day)
    ).all()

    sidechain = db.execute(
        _filters(select(ApiCall.is_sidechain, *usage_columns()), days, project_id, device).group_by(ApiCall.is_sidechain)
    ).all()

    counts_stmt = select(func.count(func.distinct(ApiCall.session_id)))
    sessions = db.scalar(_filters(counts_stmt, days, project_id, device)) or 0
    turn_stmt = select(func.count(Turn.id))
    start = since(days)
    if start is not None:
        turn_stmt = turn_stmt.where(Turn.ts >= start)
    prompts = db.scalar(scope(turn_stmt, project_id, device, Turn.session_id)) or 0

    daily_model = db.execute(
        _filters(select(day, ApiCall.model, func.coalesce(func.sum(ApiCall.cost_usd), 0.0).label("cost_usd")),
                 days, project_id, device).group_by(day, ApiCall.model).order_by(day)
    ).all()

    by_device = select(ChatSession.source.label("device"), *usage_columns()).join(
        ChatSession, ChatSession.id == ApiCall.session_id)
    if start is not None:
        by_device = by_device.where(ApiCall.ts >= start)
    by_device = db.execute(scope(by_device, project_id, device).group_by(ChatSession.source)
                           .order_by(desc("cost_usd"))).all()

    cost_by_kind = dict.fromkeys(("input", "output", "cache_write", "cache_read"), 0.0)
    for r in by_model:
        for k, v in cost_breakdown(r.model, r).items():
            cost_by_kind[k] += v

    return {
        "days": days,
        "totals": {**usage_dict(totals), "sessions": sessions, "prompts": prompts},
        "cost_by_kind": {k: round(v, 4) for k, v in cost_by_kind.items()},
        "by_model": [{"model": r.model, **usage_dict(r)} for r in by_model],
        "daily": [{"day": _iso(r.day), **usage_dict(r)} for r in daily],
        "daily_by_model": [{"day": _iso(r.day), "model": r.model, "cost_usd": round(float(r.cost_usd), 4)}
                           for r in daily_model],
        "by_thread": [{"thread": "subagents" if r.is_sidechain else "main", **usage_dict(r)} for r in sidechain],
        "by_device": [{"device": r.device, **usage_dict(r)} for r in by_device],
    }


@router.get("/projects")
def projects(db: DB, days: int = Days):
    stmt = (
        select(Project.id, Project.name, Project.path,
               func.count(func.distinct(ApiCall.session_id)).label("sessions"), *usage_columns())
        .join(ChatSession, ChatSession.project_id == Project.id)
        .join(ApiCall, ApiCall.session_id == ChatSession.id)
        .group_by(Project.id, Project.name, Project.path)
        .order_by(desc("cost_usd"))
    )
    start = since(days)
    if start is not None:
        stmt = stmt.where(ApiCall.ts >= start)
    return [
        {"id": r.id, "name": r.name, "path": r.path, "sessions": r.sessions, **usage_dict(r)}
        for r in db.execute(stmt).all()
    ]


@router.get("/sources")
def sources(db: DB, days: int = Days):
    """Devices that sent data: `wamt agent` device names and the server's own source."""
    stmt = (select(ChatSession.source.label("device"), func.count(func.distinct(ApiCall.session_id)).label("sessions"),
                   *usage_columns())
            .join(ApiCall, ApiCall.session_id == ChatSession.id)
            .group_by(ChatSession.source).order_by(desc("cost_usd")))
    start = since(days)
    if start is not None:
        stmt = stmt.where(ApiCall.ts >= start)
    return [{"device": r.device, "sessions": r.sessions, **usage_dict(r)} for r in db.execute(stmt).all()]


SESSION_SORTS = {"cost": "cost_usd", "tokens": "total", "recent": "ended_at"}


@router.get("/sessions")
def sessions(
    db: DB,
    days: int = Days,
    project_id: int | None = None,
    device: str | None = Device,
    sort: str = Query("recent", pattern="^(cost|tokens|recent)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    total_tokens = (
        func.coalesce(func.sum(ApiCall.input_tokens), 0) + func.coalesce(func.sum(ApiCall.output_tokens), 0)
        + func.coalesce(func.sum(ApiCall.cache_write_5m), 0) + func.coalesce(func.sum(ApiCall.cache_write_1h), 0)
        + func.coalesce(func.sum(ApiCall.cache_read), 0)
    ).label("total")
    stmt = (
        select(ChatSession, Project.name.label("project_name"), total_tokens, *usage_columns())
        .join(Project, Project.id == ChatSession.project_id)
        .join(ApiCall, ApiCall.session_id == ChatSession.id)
        .group_by(ChatSession.id, Project.name)
    )
    start = since(days)
    if start is not None:
        stmt = stmt.where(ChatSession.ended_at >= start)
    stmt = scope(stmt, project_id, device)
    order = SESSION_SORTS[sort]
    stmt = stmt.order_by(desc(ChatSession.ended_at) if order == "ended_at" else desc(order))
    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    return [_session_out(r.ChatSession, r.project_name) | usage_dict(r) for r in rows]


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, db: DB):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "Session not found")
    project = db.get(Project, s.project_id)
    totals = db.execute(select(*usage_columns()).where(ApiCall.session_id == session_id)).one()

    turn_usage = {
        r.turn_id: usage_dict(r)
        for r in db.execute(
            select(ApiCall.turn_id, *usage_columns()).where(ApiCall.session_id == session_id).group_by(ApiCall.turn_id)
        ).all()
    }
    tools: dict[str | None, dict[str, int]] = {}
    for r in db.execute(
        select(ToolCall.turn_id, ToolCall.name, func.count(ToolCall.id).label("n"))
        .where(ToolCall.session_id == session_id).group_by(ToolCall.turn_id, ToolCall.name)
    ).all():
        tools.setdefault(r.turn_id, {})[r.name] = int(r.n)

    turns = db.scalars(select(Turn).where(Turn.session_id == session_id).order_by(Turn.ts)).all()
    return {
        **_session_out(s, project.name if project else None),
        **usage_dict(totals),
        "models": [m for (m,) in db.execute(
            select(ApiCall.model).where(ApiCall.session_id == session_id).distinct()).all()],
        "turns": [
            {
                "id": t.id, "ts": t.ts, "prompt": t.prompt, "permission_mode": t.permission_mode,
                "category": t.category, "category_source": t.category_source,
                "category_confidence": t.category_confidence,
                "category_scores": json.loads(t.category_scores) if t.category_scores else {},
                "tools": tools.get(t.id, {}),
                **turn_usage.get(t.id, usage_dict(_empty())),
            }
            for t in turns
        ],
        "events": [
            {"ts": e.ts, "kind": e.kind, "cause": e.cause, "tokens": e.tokens, "wasted_usd": round(e.wasted_usd, 4)}
            for e in db.scalars(select(SessionEvent).where(SessionEvent.session_id == session_id)
                                .order_by(SessionEvent.ts))
        ],
    }


@router.get("/turns/top")
def top_turns(db: DB, days: int = Days, project_id: int | None = None, device: str | None = Device,
              limit: int = Query(20, ge=1, le=200)):
    stmt = (
        select(Turn.id, Turn.ts, Turn.prompt, Turn.category, Turn.session_id, ChatSession.title,
               Project.name.label("project"), *usage_columns())
        .join(ApiCall, ApiCall.turn_id == Turn.id)
        .join(ChatSession, ChatSession.id == Turn.session_id)
        .join(Project, Project.id == ChatSession.project_id)
        .group_by(Turn.id, Turn.ts, Turn.prompt, Turn.category, Turn.session_id, ChatSession.title, Project.name)
        .order_by(desc("cost_usd"))
        .limit(limit)
    )
    start = since(days)
    if start is not None:
        stmt = stmt.where(Turn.ts >= start)
    stmt = scope(stmt, project_id, device)
    return [
        {"id": r.id, "ts": r.ts, "prompt": r.prompt, "category": r.category, "session_id": r.session_id, "session_title": r.title,
         "project": r.project, **usage_dict(r)}
        for r in db.execute(stmt).all()
    ]


class _empty:
    input_tokens = output_tokens = cache_write_5m = cache_write_1h = cache_read = 0
    cost_usd = 0.0
    api_calls = 0
    unpriced_calls = 0


def _iso(v):
    return v.isoformat() if isinstance(v, date) else str(v)


def _session_out(s: ChatSession, project_name: str | None) -> dict:
    return {
        "id": s.id, "title": s.title, "project_id": s.project_id, "project": project_name, "device": s.source,
        "git_branch": s.git_branch, "entrypoint": s.entrypoint, "version": s.version,
        "started_at": s.started_at, "ended_at": s.ended_at,
    }
