"""In-memory snapshot of the data the insight miners need, loaded once per refresh."""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt.db import ApiCall, ChatSession, Project, SessionEvent, ToolCall, Turn
from wamt.pricing import price_for

MAX_CARRY_CALLS = 150


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class Tool:
    id: str
    session_id: str
    turn_id: str | None
    ts: datetime
    name: str
    target: str | None
    signature: str | None
    is_error: bool
    result_chars: int
    is_sidechain: bool

    @property
    def result_tokens(self) -> int:
        return self.result_chars // 4  # ~4 chars per token


@dataclass
class TurnInfo:
    id: str
    session_id: str
    ts: datetime
    prompt: str
    category: str | None
    cost: float = 0.0
    calls: int = 0
    models: dict[str, float] = field(default_factory=dict)  # model -> cost
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> token totals


@dataclass
class SessionInfo:
    id: str
    project_id: int
    title: str | None
    call_times: list[datetime] = field(default_factory=list)  # main-thread calls, sorted
    contexts: list[tuple[datetime, str, int]] = field(default_factory=list)  # (ts, model, context tokens)
    cost: float = 0.0
    calls: int = 0

    @property
    def cost_per_call(self) -> float:
        return self.cost / self.calls if self.calls else 0.0

    def calls_after(self, ts: datetime) -> int:
        return len(self.call_times) - bisect.bisect_right(self.call_times, ts)


@dataclass
class Dataset:
    since: datetime
    span_days: float
    projects: dict[int, tuple[str, str | None]]  # id -> (name, path)
    sessions: dict[str, SessionInfo]
    turns: dict[str, TurnInfo]
    tools: list[Tool]
    rebuilds: list[SessionEvent]

    def project_of(self, session_id: str) -> int:
        return self.sessions[session_id].project_id

    def project_name(self, project_id: int | None) -> str:
        return self.projects.get(project_id, ("all projects", None))[0] if project_id else "all projects"

    def monthly(self, usd: float) -> float:
        """Scale a total observed over the window to a 30-day figure (never extrapolates upwards)."""
        return usd * 30 / max(self.span_days, 30)


def load(db: Session, days: int = 90) -> Dataset:
    since = datetime.now(UTC) - timedelta(days=days)
    projects = {p.id: (p.name, p.path) for p in db.scalars(select(Project))}
    sessions = {
        s.id: SessionInfo(id=s.id, project_id=s.project_id, title=s.title)
        for s in db.scalars(select(ChatSession).where(ChatSession.ended_at >= since))
    }
    turns = {
        t.id: TurnInfo(id=t.id, session_id=t.session_id, ts=_aware(t.ts), prompt=t.prompt or "", category=t.category)
        for t in db.scalars(select(Turn).where(Turn.ts >= since))
        if t.session_id in sessions
    }
    first = last = None
    for r in db.execute(
        select(ApiCall.session_id, ApiCall.turn_id, ApiCall.ts, ApiCall.model, ApiCall.cost_usd, ApiCall.is_sidechain,
               ApiCall.input_tokens, ApiCall.output_tokens, ApiCall.cache_write_5m, ApiCall.cache_write_1h,
               ApiCall.cache_read)
        .where(ApiCall.ts >= since).order_by(ApiCall.ts)
    ).all():
        s = sessions.get(r.session_id)
        if s is None:
            continue
        ts = _aware(r.ts)
        first = first or ts
        last = ts
        cost = r.cost_usd or 0.0
        s.cost += cost
        s.calls += 1
        if not r.is_sidechain:
            s.call_times.append(ts)
            s.contexts.append((ts, r.model, r.input_tokens + r.cache_write_5m + r.cache_write_1h + r.cache_read))
        t = turns.get(r.turn_id) if r.turn_id else None
        if t:
            t.cost += cost
            t.calls += 1
            t.models[r.model] = t.models.get(r.model, 0.0) + cost
            m = t.by_model.setdefault(r.model, defaultdict(int))
            for f in ("input_tokens", "output_tokens", "cache_write_5m", "cache_write_1h", "cache_read"):
                m[f] += getattr(r, f)
    tools = [
        Tool(id=r.id, session_id=r.session_id, turn_id=r.turn_id, ts=_aware(r.ts), name=r.name, target=r.target,
             signature=r.signature, is_error=bool(r.is_error), result_chars=r.result_chars or 0,
             is_sidechain=bool(r.is_sidechain))
        for r in db.scalars(select(ToolCall).where(ToolCall.ts >= since).order_by(ToolCall.ts))
        if r.session_id in sessions
    ]
    rebuilds = [e for e in db.scalars(select(SessionEvent).where(SessionEvent.kind == "cache_rebuild",
                                                                 SessionEvent.ts >= since))
                if e.session_id in sessions]
    span = (last - first).total_seconds() / 86400 if first and last else 0.0
    return Dataset(since=since, span_days=span, projects=projects, sessions=sessions, turns=turns, tools=tools,
                   rebuilds=rebuilds)


def carry_cost(ds: Dataset, tool: Tool) -> float:
    """What a tool result costs over the rest of its session: written to cache once, then
    re-read by every later main-thread call. Capped, since compaction or /clear drops it sooner."""
    s = ds.sessions[tool.session_id]
    if not s.contexts:
        return 0.0
    i = max(bisect.bisect_right(s.call_times, tool.ts) - 1, 0)
    p = price_for(s.contexts[i][1])
    if p is None:
        return 0.0
    remaining = min(s.calls_after(tool.ts), MAX_CARRY_CALLS)
    return tool.result_tokens * (p.cache_write_5m + p.cache_read * remaining) / 1_000_000
