"""Incremental ingestion of Claude Code transcripts into the database.

Each file's byte offset is stored, so a scan only parses lines appended since the
previous one. Only complete (newline-terminated) lines are consumed; a half-written
line is picked up on the next scan.
"""

from __future__ import annotations

import bisect
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt.analytics.enrich import enrich
from wamt.collector.parser import (
    BUILTIN_COMMANDS,
    Event,
    Parsed,
    Prompt,
    SessionMeta,
    ToolResult,
    Usage,
    parse_line,
    slash_command,
)
from wamt.config import get_settings
from wamt.db import (
    ApiCall,
    ChatSession,
    IngestFile,
    Project,
    SessionEvent,
    ToolCall,
    Turn,
    get_meta,
    new_session,
    set_meta,
)
from wamt.pricing import cost_usd

log = logging.getLogger(__name__)
CHUNK_BYTES = 8 * 1024 * 1024
PARSER_VERSION = "2"  # bump when parsing changes so stored data is re-read


@dataclass
class IngestStatus:
    running: bool = False
    files_seen: int = 0
    files_changed: int = 0
    last_scan_at: datetime | None = None
    last_scan_seconds: float = 0.0
    last_error: str | None = None
    lines_total: int = 0


STATUS = IngestStatus()


@dataclass
class Batch:
    metas: dict[str, SessionMeta] = field(default_factory=dict)
    first_ts: dict[str, datetime] = field(default_factory=dict)
    prompts: dict[str, Prompt] = field(default_factory=dict)
    usages: dict[str, Usage] = field(default_factory=dict)
    results: dict[str, ToolResult] = field(default_factory=dict)
    events: dict[str, Event] = field(default_factory=dict)

    def add(self, p: Parsed) -> None:
        if p.meta:
            m = p.meta
            cur = self.metas.get(m.session_id)
            if cur is None:
                self.metas[m.session_id] = m
            else:
                for f in ("cwd", "git_branch", "entrypoint", "version", "title"):
                    if getattr(m, f):
                        setattr(cur, f, getattr(m, f))
                if m.ts and (cur.ts is None or m.ts > cur.ts):
                    cur.ts = m.ts
            if m.ts:
                first = self.first_ts.get(m.session_id)
                if first is None or m.ts < first:
                    self.first_ts[m.session_id] = m.ts
        if p.prompt:
            self.prompts[p.prompt.id] = p.prompt
        if p.usage:
            existing = self.usages.get(p.usage.message_id)
            if existing:
                existing.merge(p.usage)
            else:
                self.usages[p.usage.message_id] = p.usage
        for r in p.results:
            self.results[r.tool_use_id] = r
        if p.event:
            self.events[p.event.id] = p.event


def project_slug(file: Path, root: Path) -> str:
    rel = PurePath(file).relative_to(root)
    return rel.parts[0] if len(rel.parts) > 1 else "_root"


def _project_name(cwd: str | None, slug: str) -> str:
    if cwd:
        return PurePath(cwd.replace("\\", "/")).name or slug
    return slug


def slugify(path: str) -> str:
    """Claude Code's project directory name for a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _matches(cwd: str | None, slug: str) -> bool:
    return bool(cwd) and slugify(cwd).lower() == slug.lower()


def _get_project(db: Session, slug: str, cwds: list[str]) -> Project:
    # The cwd can move into subdirectories mid-session; the project root is the one
    # whose slug matches the transcript directory.
    cwd = next((c for c in cwds if _matches(c, slug)), cwds[0] if cwds else None)
    proj = db.scalar(select(Project).where(Project.slug == slug))
    if proj is None:
        proj = Project(slug=slug, path=cwd, name=_project_name(cwd, slug))
        db.add(proj)
        db.flush()
    elif cwd and (not proj.path or (_matches(cwd, slug) and not _matches(proj.path, slug))):
        proj.path = cwd
        proj.name = _project_name(cwd, slug)
    return proj


def write_batch(db: Session, batch: Batch, slug: str, source: str) -> None:
    if not batch.metas:
        return
    touched_turns: set[str] = set(batch.prompts)
    proj = _get_project(db, slug, [m.cwd for m in batch.metas.values() if m.cwd])

    for sid, m in batch.metas.items():
        s = db.get(ChatSession, sid)
        if s is None:
            s = ChatSession(id=sid, project_id=proj.id, source=source)
            db.add(s)
        for f in ("cwd", "git_branch", "entrypoint", "version", "title"):
            v = getattr(m, f)
            if v:
                setattr(s, f, v)
        first = batch.first_ts.get(sid)
        if first and (s.started_at is None or _aware(s.started_at) > first):
            s.started_at = first
        if m.ts and (s.ended_at is None or _aware(s.ended_at) < m.ts):
            s.ended_at = m.ts
    db.flush()

    store = get_settings().store_prompts
    for pid, p in batch.prompts.items():
        text = p.text if store else None  # privacy mode: only the length is kept
        turn = db.get(Turn, pid)
        if turn is None:
            db.add(Turn(id=pid, session_id=p.session_id, ts=p.ts, prompt=text,
                        prompt_chars=len(p.text), permission_mode=p.permission_mode))
        elif turn.prompt != text:  # re-parsed with newer cleaning rules, or privacy mode switched on
            turn.prompt, turn.prompt_chars = text, len(p.text)

    for mid, u in batch.usages.items():
        row = db.get(ApiCall, mid)
        if row is None:
            row = ApiCall(id=mid, session_id=u.session_id, ts=u.ts, model=u.model,
                          is_sidechain=u.is_sidechain, agent_id=u.agent_id,
                          service_tier=u.service_tier)
            db.add(row)
            for f in ("input_tokens", "output_tokens", "cache_write_5m", "cache_write_1h",
                      "cache_read", "web_search_requests"):
                setattr(row, f, getattr(u, f))
        else:
            for f in ("input_tokens", "output_tokens", "cache_write_5m", "cache_write_1h",
                      "cache_read", "web_search_requests"):
                setattr(row, f, max(getattr(row, f) or 0, getattr(u, f)))
        row.cost_usd = cost_usd(row.model, row.input_tokens, row.output_tokens,
                                row.cache_write_5m, row.cache_write_1h, row.cache_read)
        for t in u.tools:
            if db.get(ToolCall, t.id) is None:
                db.add(ToolCall(id=t.id, api_call_id=mid, session_id=u.session_id, ts=u.ts,
                                name=t.name, target=t.target, is_sidechain=u.is_sidechain))
    db.flush()

    for tid, r in batch.results.items():
        tc = db.get(ToolCall, tid)
        if tc is not None:
            tc.is_error = r.is_error
            tc.result_chars = r.chars
            if tc.turn_id:
                touched_turns.add(tc.turn_id)

    for eid, e in batch.events.items():
        if db.scalar(select(SessionEvent.id).where(SessionEvent.ref_id == eid)) is None:
            db.add(SessionEvent(session_id=e.session_id, ts=e.ts, kind=e.kind, ref_id=eid, cause=e.cause,
                                tokens=e.tokens))

    touched_turns |= assign_turns(db, set(batch.metas))
    db.flush()
    # Prompt text is passed in memory so categories work even when prompts aren't stored.
    enrich(db, set(batch.metas), touched_turns, {pid: p.text for pid, p in batch.prompts.items()})


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; everything we store is UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def assign_turns(db: Session, session_ids: set[str]) -> set[str]:
    """Attach unassigned API/tool calls to the latest human prompt that precedes them.

    Assistant records carry no prompt id, so attribution is by timestamp. Subagent
    (sidechain) calls land in the parent turn that spawned them. Returns the turns that changed.
    """
    touched: set[str] = set()
    for sid in session_ids:
        turns = db.execute(select(Turn.ts, Turn.id).where(Turn.session_id == sid).order_by(Turn.ts)).all()
        if not turns:
            continue
        times = [_aware(t.ts) for t in turns]
        ids = [t.id for t in turns]
        for model in (ApiCall, ToolCall):
            rows = db.scalars(select(model).where(model.session_id == sid, model.turn_id.is_(None))).all()
            for row in rows:
                i = bisect.bisect_right(times, _aware(row.ts)) - 1
                row.turn_id = ids[i] if i >= 0 else ids[0]
                touched.add(row.turn_id)
    return touched


def ingest_file(db: Session, file: Path, root: Path, source: str) -> int:
    """Parse new lines of one file. Returns the number of lines consumed."""
    st = file.stat()
    key = str(file)
    state = db.get(IngestFile, key)
    if state is None:
        state = IngestFile(path=key, source=source, offset=0, size=0, mtime=0)
        db.add(state)
    if st.st_size < state.offset:  # file was rewritten: start over (dedupe makes this safe)
        state.offset = 0
    if st.st_size == state.offset:
        state.size, state.mtime = st.st_size, st.st_mtime
        return 0

    slug = project_slug(file, root)
    consumed = 0
    with file.open("rb") as fh:
        fh.seek(state.offset)
        while True:
            chunk = fh.read(CHUNK_BYTES)
            if not chunk:
                break
            end = chunk.rfind(b"\n")
            if end == -1:
                if len(chunk) < CHUNK_BYTES:
                    break  # trailing partial line, wait for the writer
                # A single line bigger than the chunk: extend until its newline.
                rest = fh.readline()
                chunk += rest
                end = chunk.rfind(b"\n")
                if end == -1:
                    break
            complete = chunk[: end + 1]
            batch = Batch()
            for raw in complete.split(b"\n"):
                parsed = parse_line(raw.decode("utf-8", errors="replace"))
                if parsed:
                    batch.add(parsed)
                    consumed += 1
            write_batch(db, batch, slug, source)
            state.offset += len(complete)
            fh.seek(state.offset)
            db.commit()
    state.size, state.mtime = st.st_size, st.st_mtime
    db.commit()
    return consumed


def scan(root: Path | None = None, source: str | None = None) -> int:
    settings = get_settings()
    root = Path(root or settings.claude_data_dir)
    source = source or settings.source_name
    started = time.monotonic()
    if not root.exists():
        STATUS.last_error = f"Transcript directory not found: {root}"
        log.warning(STATUS.last_error)
        return 0
    files = sorted(root.rglob("*.jsonl"))
    changed = lines = 0
    with new_session() as db:
        known = {f.path: f for f in db.scalars(select(IngestFile)).all()}
        for f in files:
            try:
                st = f.stat()
                k = known.get(str(f))
                if k and k.size == st.st_size and k.mtime == st.st_mtime:
                    continue
                n = ingest_file(db, f, root, source)
                changed += 1
                lines += n
            except Exception as e:  # keep scanning other files
                db.rollback()
                STATUS.last_error = f"{f}: {e!r}"
                log.exception("Failed to ingest %s", f)
    STATUS.files_seen = len(files)
    STATUS.files_changed = changed
    STATUS.lines_total += lines
    STATUS.last_scan_at = datetime.now(UTC)
    STATUS.last_scan_seconds = round(time.monotonic() - started, 3)
    if changed:
        log.info("Ingested %d lines from %d files in %.2fs", lines, changed, STATUS.last_scan_seconds)
    return lines


def reparse_if_needed() -> bool:
    """Re-read every transcript when the parser changed (PARSER_VERSION).

    Non-destructive on purpose: Claude Code deletes old transcripts (cleanupPeriodDays),
    so the database may hold history that no longer exists on disk. Re-parsing only
    updates/adds rows; ids and dedupe make it idempotent.
    """
    with new_session() as db:
        if get_meta(db, "parser_version") == PARSER_VERSION:
            return False
        log.info("Parser changed: re-reading all transcripts")
        _drop_command_turns(db)
        for f in db.scalars(select(IngestFile)):
            f.offset, f.size, f.mtime = 0, 0, 0
        set_meta(db, "parser_version", PARSER_VERSION)
        db.commit()
    return True


def _drop_command_turns(db: Session) -> None:
    """Turns stored by older versions for built-in slash commands (/model, /compact...)."""
    stale = [t for t in db.scalars(select(Turn).where(Turn.prompt.contains("<command-name>")))
             if (cmd := slash_command(t.prompt)) and cmd[0] in BUILTIN_COMMANDS]
    if not stale:
        return
    ids = [t.id for t in stale]
    for model in (ApiCall, ToolCall):
        for row in db.scalars(select(model).where(model.turn_id.in_(ids))):
            row.turn_id = None
    sessions = {t.session_id for t in stale}
    for t in stale:
        db.delete(t)
    db.flush()
    assign_turns(db, sessions)


def run_forever(stop: threading.Event) -> None:
    from wamt.alerts import check_safely
    from wamt.analytics.enrich import backfill
    from wamt.insights.engine import refresh_if_due

    interval = get_settings().scan_interval
    STATUS.running = True
    reparse_if_needed()
    while not stop.is_set():
        try:
            lines = scan()
            backfill()  # no-op unless the derived-data version changed
            refresh_if_due(changed=lines > 0)
            check_safely()
        except Exception as e:
            STATUS.last_error = repr(e)
            log.exception("Scan failed")
        stop.wait(interval)
    STATUS.running = False


def reprice() -> int:
    """Recompute cost for every API call after pricing.yaml changed."""
    from wamt.pricing import load_prices

    load_prices.cache_clear()
    n = 0
    with new_session() as db:
        for row in db.scalars(select(ApiCall)).yield_per(2000):
            row.cost_usd = cost_usd(row.model, row.input_tokens, row.output_tokens,
                                    row.cache_write_5m, row.cache_write_1h, row.cache_read)
            n += 1
        db.commit()
    return n
