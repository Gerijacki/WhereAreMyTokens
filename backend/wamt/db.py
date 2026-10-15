import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from wamt.config import get_settings


class Base(DeclarativeBase):
    pass


class IngestFile(Base):
    """Read position per transcript file, so scans only parse appended lines."""

    __tablename__ = "ingest_files"
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    source: Mapped[str] = mapped_column(String(128))
    offset: Mapped[int] = mapped_column(Integer, default=0)
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime: Mapped[float] = mapped_column(Float, default=0)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(512), unique=True)
    path: Mapped[str | None] = mapped_column(String(1024))
    name: Mapped[str] = mapped_column(String(256))


class ChatSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source: Mapped[str] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(512))
    cwd: Mapped[str | None] = mapped_column(String(1024))
    git_branch: Mapped[str | None] = mapped_column(String(256))
    entrypoint: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Turn(Base):
    """A human prompt and all the assistant work it triggered until the next prompt."""

    __tablename__ = "turns"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid of the prompt record
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    prompt: Mapped[str | None] = mapped_column(Text)
    prompt_chars: Mapped[int] = mapped_column(Integer, default=0)
    permission_mode: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    category_source: Mapped[str | None] = mapped_column(String(16))  # "rules" | "manual"
    category_confidence: Mapped[float | None] = mapped_column(Float)
    category_scores: Mapped[str | None] = mapped_column(Text)  # JSON {category: score}, explains the pick


class ApiCall(Base):
    """One API response. Deduplicated by message id: transcripts repeat usage once per content block."""

    __tablename__ = "api_calls"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model: Mapped[str] = mapped_column(String(128), index=True)
    is_sidechain: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_5m: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_1h: Mapped[int] = mapped_column(Integer, default=0)
    cache_read: Mapped[int] = mapped_column(Integer, default=0)
    web_search_requests: Mapped[int] = mapped_column(Integer, default=0)
    service_tier: Mapped[str | None] = mapped_column(String(32))
    cost_usd: Mapped[float | None] = mapped_column(Float)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # tool_use id
    api_call_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str | None] = mapped_column(Text)  # bash command, file path, pattern, url...
    is_sidechain: Mapped[bool] = mapped_column(Boolean, default=False)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    result_chars: Mapped[int] = mapped_column(Integer, default=0)
    # Normalized form used for grouping: "pnpm typecheck" for shell commands, a project-relative
    # path for file tools. Lets repeated actions be counted despite cd prefixes and output pipes.
    signature: Mapped[str | None] = mapped_column(String(512), index=True)


class SessionEvent(Base):
    """Derived per-session events: compactions and cache rebuilds."""

    __tablename__ = "session_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # compact | cache_rebuild
    ref_id: Mapped[str | None] = mapped_column(String(128), index=True)  # api call id or record uuid
    model: Mapped[str | None] = mapped_column(String(128))
    cause: Mapped[str | None] = mapped_column(String(64))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    wasted_usd: Mapped[float] = mapped_column(Float, default=0.0)
    gap_seconds: Mapped[float | None] = mapped_column(Float)


class Insight(Base):
    """An automation / savings recommendation produced by the insight miners."""

    __tablename__ = "insights"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # stable hash of type + key
    type: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))  # high | medium | low
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    est_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_usd: Mapped[float] = mapped_column(Float, default=0.0)
    est_usd_month: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    artifact_kind: Mapped[str | None] = mapped_column(String(32))
    artifact_path: Mapped[str | None] = mapped_column(String(512))
    artifact_content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Meta(Base):
    __tablename__ = "meta"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Device(Base):
    """A machine that pushes transcripts with `wamt agent`. Only a hash of its token is stored."""

    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class OtelPoint(Base):
    """A Claude Code OpenTelemetry metric point or `api_request` event (PII attributes dropped)."""

    __tablename__ = "otel_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))  # metric | event
    name: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(128))
    type: Mapped[str | None] = mapped_column(String(32))  # token type for token.usage
    value: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read: Mapped[int] = mapped_column(Integer, default=0)
    cache_write: Mapped[int] = mapped_column(Integer, default=0)
    attrs: Mapped[str] = mapped_column(Text, default="{}")


Index("ix_api_calls_session_ts", ApiCall.session_id, ApiCall.ts)
Index("ix_tool_calls_session_ts", ToolCall.session_id, ToolCall.ts)

MIGRATIONS = Path(__file__).with_name("migrations")
BASELINE_REVISION = "0001"
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    _engine = create_engine(url, pool_pre_ping=True, **kwargs)
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    migrate(_engine)
    return _engine


def migrate(eng: Engine) -> None:
    """Bring the schema to the latest Alembic revision.

    Databases created before Alembic (v0.1, create_all) are first completed with any missing
    columns, then stamped as the baseline so later revisions apply on top of them.
    """
    from alembic import command
    from alembic.config import Config

    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)  # quiet plugin chatter
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    tables = set(inspect(eng).get_table_names())
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        if "alembic_version" not in tables and "api_calls" in tables:
            _complete_legacy_schema(conn)
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")


# Tables that existed at the baseline revision.
_BASELINE_TABLES = ("ingest_files", "projects", "sessions", "turns", "api_calls", "tool_calls", "session_events",
                    "insights", "meta")


def _complete_legacy_schema(conn) -> None:
    """Databases from before Alembic were built with create_all() plus columns added in place.
    Create whatever baseline table/column/index such a database is missing, so stamping it as
    the baseline is truthful."""
    tables = [Base.metadata.tables[n] for n in _BASELINE_TABLES]
    Base.metadata.create_all(conn, tables=tables)
    insp = inspect(conn)
    for table in tables:
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing:
                ddl = col.type.compile(dialect=conn.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))
        for idx in table.indexes:
            idx.create(conn, checkfirst=True)


def get_meta(db: Session, key: str) -> str | None:
    row = db.get(Meta, key)
    return row.value if row else None


def set_meta(db: Session, key: str, value: str) -> None:
    row = db.get(Meta, key)
    if row is None:
        db.add(Meta(key=key, value=value))
    else:
        row.value = value


def engine() -> Engine:
    return _engine or init_engine()


def new_session() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    with new_session() as s:
        yield s
