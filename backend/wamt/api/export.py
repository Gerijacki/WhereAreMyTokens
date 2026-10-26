"""CSV/JSON exports of sessions, prompts and daily costs, for billing clients or analysis elsewhere.

Costs are API-equivalent USD, plus `cost_eur` at the configured rate when the display currency is EUR.
Prompt text is whatever was stored: redacted, and empty with WAMT_STORE_PROMPTS=false.
"""

import csv
import io
import json
from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt.api.queries import TOKEN_COLUMNS, day_bucket, scope, since, usage_columns, usage_dict
from wamt.db import ApiCall, ChatSession, Project, Turn, get_db
from wamt.preferences import effective

router = APIRouter(prefix="/api/export")
DB = Annotated[Session, Depends(get_db)]
Days = Query(30, ge=0, le=3650, description="Look-back window in days; 0 = all time")
USAGE_FIELDS = [*TOKEN_COLUMNS, "total_tokens", "api_calls", "cost_usd"]


def _scoped(stmt, days: int, project_id: int | None, device: str | None):
    start = since(days)
    if start is not None:
        stmt = stmt.where(ApiCall.ts >= start)
    return scope(stmt, project_id, device)  # every dataset already joins ChatSession


def _sessions(db: Session, days: int, project_id: int | None, device: str | None) -> tuple[list[str], Iterator[dict]]:
    stmt = (select(ChatSession.id, Project.name.label("project"), ChatSession.source, ChatSession.title,
                   ChatSession.git_branch, ChatSession.started_at, ChatSession.ended_at, *usage_columns())
            .join(Project, Project.id == ChatSession.project_id)
            .join(ApiCall, ApiCall.session_id == ChatSession.id)
            .group_by(ChatSession.id, Project.name, ChatSession.source, ChatSession.title,
                      ChatSession.git_branch, ChatSession.started_at, ChatSession.ended_at)
            .order_by(ChatSession.started_at))
    fields = ["session_id", "project", "device", "title", "git_branch", "started_at", "ended_at", *USAGE_FIELDS]
    rows = ({"session_id": r.id, "project": r.project, "device": r.source, "title": r.title, "git_branch": r.git_branch,
             "started_at": r.started_at, "ended_at": r.ended_at, **usage_dict(r)}
            for r in db.execute(_scoped(stmt, days, project_id, device)))
    return fields, rows


def _prompts(db: Session, days: int, project_id: int | None, device: str | None) -> tuple[list[str], Iterator[dict]]:
    stmt = (select(Turn.id, Turn.session_id, Project.name.label("project"), Turn.ts, Turn.category, Turn.prompt,
                   *usage_columns())
            .join(ApiCall, ApiCall.turn_id == Turn.id)
            .join(ChatSession, ChatSession.id == Turn.session_id)
            .join(Project, Project.id == ChatSession.project_id)
            .group_by(Turn.id, Turn.session_id, Project.name, Turn.ts, Turn.category, Turn.prompt)
            .order_by(Turn.ts))
    fields = ["prompt_id", "session_id", "project", "ts", "category", "prompt", *USAGE_FIELDS]
    rows = ({"prompt_id": r.id, "session_id": r.session_id, "project": r.project, "ts": r.ts,
             "category": r.category, "prompt": r.prompt, **usage_dict(r)}
            for r in db.execute(_scoped(stmt, days, project_id, device)))
    return fields, rows


def _daily(db: Session, days: int, project_id: int | None, device: str | None) -> tuple[list[str], Iterator[dict]]:
    day = day_bucket(db, ApiCall.ts).label("day")
    stmt = (select(day, Project.name.label("project"), ApiCall.model, *usage_columns())
            .join(ChatSession, ChatSession.id == ApiCall.session_id)
            .join(Project, Project.id == ChatSession.project_id)
            .group_by(day, Project.name, ApiCall.model)
            .order_by(day, Project.name, ApiCall.model))
    fields = ["day", "project", "model", *USAGE_FIELDS]
    rows = ({"day": r.day, "project": r.project, "model": r.model, **usage_dict(r)}
            for r in db.execute(_scoped(stmt, days, project_id, device)))
    return fields, rows


DATASETS = {"sessions": _sessions, "prompts": _prompts, "daily": _daily}


def _plain(v):
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


@router.get("/{dataset}.{fmt}")
def export(dataset: str, fmt: str, db: DB, days: int = Days, project_id: int | None = None,
           device: str | None = None):
    if dataset not in DATASETS or fmt not in ("csv", "json"):
        raise HTTPException(404, f"Export as /api/export/<{'|'.join(DATASETS)}>.<csv|json>")
    fields, rows = DATASETS[dataset](db, days, project_id, device)
    prefs = effective(db)
    if prefs["currency"] == "EUR":
        fields = [*fields, "cost_eur"]
        rate = prefs["eur_per_usd"]
        rows = ({**r, "cost_eur": round(r["cost_usd"] * rate, 4)} for r in rows)
    # Read everything before responding: the request's DB session may close before a stream ends.
    rows = [{f: _plain(r.get(f)) for f in fields} for r in rows]
    name = f"wamt-{dataset}{f'-{device}' if device else ''}-{'all' if days == 0 else f'{days}d'}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}

    if fmt == "json":
        return StreamingResponse(iter([json.dumps(rows, ensure_ascii=False)]), media_type="application/json",
                                 headers=headers)

    def csv_lines() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
            if buf.tell() > 64_000:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    return StreamingResponse(csv_lines(), media_type="text/csv; charset=utf-8", headers=headers)
