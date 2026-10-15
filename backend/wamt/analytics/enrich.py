"""Derived data computed after ingestion: tool signatures, turn categories, cache rebuilds.

`enrich()` runs for the sessions/turns touched by each ingest batch. `backfill()` redoes
everything when ENRICH_VERSION changes (new rules or algorithms) so old data catches up.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from wamt.analytics.cache import Call, detect_rebuilds
from wamt.analytics.classify import TurnFacts, classify, facts_json, load_rules
from wamt.analytics.commands import SHELL_TOOLS, tool_signature
from wamt.collector.parser import clean_prompt
from wamt.db import (
    ApiCall,
    ChatSession,
    Project,
    SessionEvent,
    ToolCall,
    Turn,
    get_meta,
    new_session,
    set_meta,
)

log = logging.getLogger(__name__)
ENRICH_VERSION = "5"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _project_roots(db: Session, session_ids: set[str]) -> dict[str, str | None]:
    rows = db.execute(
        select(ChatSession.id, Project.path).join(Project, Project.id == ChatSession.project_id)
        .where(ChatSession.id.in_(session_ids))
    ).all()
    return {r.id: r.path for r in rows}


def sign_tools(db: Session, session_ids: set[str], only_missing: bool = True) -> None:
    roots = _project_roots(db, session_ids)
    stmt = select(ToolCall).where(ToolCall.session_id.in_(session_ids))
    if only_missing:
        stmt = stmt.where(ToolCall.signature.is_(None))
    for tc in db.scalars(stmt):
        sig = tool_signature(tc.name, tc.target, roots.get(tc.session_id))
        tc.signature = sig[:512] if sig else None


def turn_facts(db: Session, turns: list[Turn], prompt_texts: dict[str, str] | None = None) -> dict[str, TurnFacts]:
    texts = prompt_texts or {}
    facts = {t.id: TurnFacts(prompt=texts.get(t.id) or t.prompt or "", permission_mode=t.permission_mode)
             for t in turns}
    if not facts:
        return facts
    rows = db.execute(
        select(ToolCall.turn_id, ToolCall.name, ToolCall.signature, ToolCall.target, ToolCall.is_error)
        .where(ToolCall.turn_id.in_(list(facts))).order_by(ToolCall.ts)
    ).all()
    failed: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        f = facts[r.turn_id]
        f.tools[r.name] += 1
        if r.is_error:
            f.errors += 1
        if r.name in SHELL_TOOLS and r.signature:
            f.commands.append(r.signature)
            if r.signature in failed[r.turn_id]:
                f.repeated_after_error += 1
            if r.is_error:
                failed[r.turn_id].add(r.signature)
        if r.name in ("Edit", "Write", "MultiEdit") and (r.target or "").lower().endswith((".md", ".mdx", ".rst")):
            f.markdown_edits += 1
    return facts


def classify_turns(db: Session, turn_ids: set[str] | None = None, session_ids: set[str] | None = None,
                   prompt_texts: dict[str, str] | None = None) -> int:
    stmt = select(Turn).where((Turn.category_source.is_(None)) | (Turn.category_source != "manual"))
    if turn_ids is not None:
        stmt = stmt.where(Turn.id.in_(turn_ids))
    if session_ids is not None:
        stmt = stmt.where(Turn.session_id.in_(session_ids))
    turns = list(db.scalars(stmt))
    n = 0
    for chunk in range(0, len(turns), 500):
        part = turns[chunk:chunk + 500]
        facts = turn_facts(db, part, prompt_texts)
        for t in part:
            cat, conf, scores = classify(facts[t.id])
            t.category, t.category_confidence = cat, conf
            t.category_scores, t.category_source = facts_json(scores), "rules"
            n += 1
    return n


def cache_events(db: Session, session_ids: set[str]) -> None:
    for sid in session_ids:
        calls = [
            Call(id=r.id, ts=_aware(r.ts), model=r.model, input_tokens=r.input_tokens,
                 cache_write_5m=r.cache_write_5m, cache_write_1h=r.cache_write_1h, cache_read=r.cache_read)
            for r in db.execute(
                select(ApiCall.id, ApiCall.ts, ApiCall.model, ApiCall.input_tokens, ApiCall.cache_write_5m,
                       ApiCall.cache_write_1h, ApiCall.cache_read)
                .where(ApiCall.session_id == sid, ApiCall.is_sidechain.is_(False))
            ).all()
        ]
        compactions = [_aware(ts) for (ts,) in db.execute(
            select(SessionEvent.ts).where(SessionEvent.session_id == sid, SessionEvent.kind == "compact")).all()]
        db.execute(delete(SessionEvent).where(SessionEvent.session_id == sid, SessionEvent.kind == "cache_rebuild"))
        for rb in detect_rebuilds(calls, compactions):
            db.add(SessionEvent(session_id=sid, ts=rb.ts, kind="cache_rebuild", ref_id=rb.call_id, model=rb.model,
                                cause=rb.cause, tokens=rb.tokens, wasted_usd=rb.wasted_usd,
                                gap_seconds=rb.gap_seconds))


def enrich(db: Session, session_ids: set[str], turn_ids: set[str], prompt_texts: dict[str, str] | None = None) -> None:
    if not session_ids:
        return
    sign_tools(db, session_ids)
    classify_turns(db, turn_ids=turn_ids, prompt_texts=prompt_texts)
    cache_events(db, session_ids)


def backfill(force: bool = False) -> bool:
    """Recompute all derived data once per ENRICH_VERSION (or when forced)."""
    with new_session() as db:
        if not force and get_meta(db, "enrich_version") == ENRICH_VERSION:
            return False
        load_rules.cache_clear()
        sids = set(db.scalars(select(ChatSession.id)))
        for t in db.scalars(select(Turn).where(Turn.prompt.contains("<"))):
            cleaned = clean_prompt(t.prompt)
            if cleaned != t.prompt:
                t.prompt, t.prompt_chars = cleaned, len(cleaned)
        log.info("Backfilling derived data for %d sessions", len(sids))
        sign_tools(db, sids, only_missing=False)
        db.flush()
        n = classify_turns(db)
        cache_events(db, sids)
        set_meta(db, "enrich_version", ENRICH_VERSION)
        db.commit()
        log.info("Backfill done: %d turns classified", n)
        return True
