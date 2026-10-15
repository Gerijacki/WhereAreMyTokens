"""Turn raw Claude Code transcript records (one JSON object per JSONL line) into typed facts.

Pure functions only - no database access - so the format quirks are easy to unit test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from wamt.collector.redact import redact

# Prompts injected by the harness rather than typed by a human.
_NON_HUMAN_PREFIXES = (
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<task-notification>",
    "<system-reminder>",
    "[Request interrupted by user",
    "Caveat: The messages below were generated",
)
# Context blocks the IDE extensions / harness prepend to a prompt; not what the user typed.
_HARNESS_TAGS = r"ide_[a-z_]+|browser_instruction|system-reminder|[a-z_]+_context"
HARNESS_BLOCKS = re.compile(rf"<({_HARNESS_TAGS})>.*?</\1>\s*", re.DOTALL)
# A block whose closing tag was lost (e.g. text truncated by an older version).
_UNCLOSED_BLOCK = re.compile(rf"<({_HARNESS_TAGS})>(?!.*</\1>).*\Z", re.DOTALL)
_COMMAND_NAME = re.compile(r"<command-name>(/[\w:-]+)</command-name>")
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# Built-in Claude Code commands that control the session rather than ask for work.
BUILTIN_COMMANDS = {
    "/model", "/compact", "/clear", "/cost", "/help", "/config", "/login", "/logout", "/resume", "/status",
    "/permissions", "/memory", "/mcp", "/hooks", "/agents", "/context", "/usage", "/exit", "/doctor", "/vim",
    "/theme", "/terminal-setup", "/output-style", "/add-dir", "/bashes", "/export", "/rewind", "/ide",
    "/fast", "/plugin", "/statusline", "/upgrade", "/release-notes", "/privacy-settings", "/todos", "/effort",
}
_NON_HUMAN_ORIGINS = {"task-notification", "peer", "auto-continuation"}
_SKIP_MODELS = {"<synthetic>"}
MAX_PROMPT_CHARS = 4000


@dataclass
class SessionMeta:
    session_id: str
    cwd: str | None = None
    git_branch: str | None = None
    entrypoint: str | None = None
    version: str | None = None
    title: str | None = None
    ts: datetime | None = None


@dataclass
class Prompt:
    id: str
    session_id: str
    ts: datetime
    text: str
    permission_mode: str | None


@dataclass
class ToolUse:
    id: str
    name: str
    target: str | None


@dataclass
class Usage:
    message_id: str
    session_id: str
    ts: datetime
    model: str
    is_sidechain: bool
    agent_id: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    web_search_requests: int = 0
    service_tier: str | None = None
    tools: list[ToolUse] = field(default_factory=list)

    def merge(self, other: Usage) -> None:
        """Combine two records of the same API response (one line per content block).

        Usage is repeated on every line and may grow while streaming, so keep the max.
        """
        for f in ("input_tokens", "output_tokens", "cache_write_5m", "cache_write_1h",
                  "cache_read", "web_search_requests"):
            setattr(self, f, max(getattr(self, f), getattr(other, f)))
        known = {t.id for t in self.tools}
        self.tools.extend(t for t in other.tools if t.id not in known)
        self.ts = min(self.ts, other.ts)


@dataclass
class ToolResult:
    tool_use_id: str
    is_error: bool
    chars: int


@dataclass
class Event:
    id: str
    session_id: str
    ts: datetime
    kind: str  # "compact" | "command"
    cause: str | None = None  # compaction trigger (manual | auto) or the command line
    tokens: int = 0  # context size before compaction


@dataclass
class Parsed:
    meta: SessionMeta | None = None
    prompt: Prompt | None = None
    usage: Usage | None = None
    results: list[ToolResult] = field(default_factory=list)
    event: Event | None = None


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def tool_target(name: str, inp: dict) -> str | None:
    """The single most informative argument of a tool call, used for pattern mining."""
    if not isinstance(inp, dict):
        return None
    for key in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query",
                "skill", "subagent_type", "description", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            return _redact(v[:2000])
    return None


def _redact(text: str) -> str:
    from wamt.config import get_settings

    return redact(text) if get_settings().redact_secrets else text


def _content_chars(content) -> int:
    if isinstance(content, dict) and "chars" in content:  # slimmed by the agent
        return int(content["chars"])
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                total += len(block.get("text") or "") if block.get("type") == "text" else 0
        return total
    return 0


def slash_command(text: str) -> tuple[str, str] | None:
    """('/review', 'args') for a slash-command invocation record, else None."""
    m = _COMMAND_NAME.search(text)
    if not m:
        return None
    args = _COMMAND_ARGS.search(text)
    return m.group(1), (args.group(1).strip() if args else "")


def clean_prompt(text: str) -> str:
    return _UNCLOSED_BLOCK.sub("", HARNESS_BLOCKS.sub("", text)).strip()


def _prompt_text(record: dict) -> str | None:
    """Return the text of a human-typed prompt, or None for tool results / harness messages."""
    if record.get("isSidechain") or record.get("isMeta") or record.get("isCompactSummary"):
        return None
    if record.get("isVisibleInTranscriptOnly"):
        return None
    origin = record.get("origin") or {}
    if origin.get("kind") in _NON_HUMAN_ORIGINS:
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    else:
        return None
    text = clean_prompt(text)
    if not text or text.startswith(_NON_HUMAN_PREFIXES):
        return None
    return text


def parse_record(record: dict) -> Parsed:
    out = Parsed()
    session_id = record.get("sessionId")
    if not session_id:
        return out
    ts = parse_ts(record.get("timestamp"))
    rtype = record.get("type")

    if rtype == "ai-title" and record.get("aiTitle"):
        out.meta = SessionMeta(session_id=session_id, title=record["aiTitle"])
        return out
    if ts is None:
        return out

    out.meta = SessionMeta(
        session_id=session_id,
        cwd=record.get("cwd"),
        git_branch=record.get("gitBranch"),
        entrypoint=record.get("entrypoint"),
        version=record.get("version"),
        ts=ts,
    )

    if rtype == "system" and record.get("subtype") == "compact_boundary" and record.get("uuid"):
        cm = record.get("compactMetadata") or {}
        out.event = Event(id=record["uuid"], session_id=session_id, ts=ts, kind="compact",
                          cause=cm.get("trigger"), tokens=int(cm.get("preTokens") or 0))

    if rtype == "user":
        content = (record.get("message") or {}).get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                    out.results.append(ToolResult(
                        tool_use_id=b["tool_use_id"],
                        is_error=bool(b.get("is_error")),
                        chars=_content_chars(b.get("content")),
                    ))
        text = _prompt_text(record)
        cmd = slash_command(text) if text else None
        if cmd and cmd[0] in BUILTIN_COMMANDS:
            # /model, /compact, /clear... are session controls, not work prompts.
            if record.get("uuid"):
                out.event = Event(id=record["uuid"], session_id=session_id, ts=ts, kind="command",
                                  cause=f"{cmd[0]} {cmd[1]}".strip()[:64])
            text = None
        elif cmd:
            text = f"{cmd[0]} {cmd[1]}".strip()
        if text is not None and record.get("uuid"):
            out.prompt = Prompt(
                id=record["uuid"],
                session_id=session_id,
                ts=ts,
                text=_redact(text[:MAX_PROMPT_CHARS]),
                permission_mode=record.get("permissionMode"),
            )

    elif rtype == "assistant":
        msg = record.get("message") or {}
        model = msg.get("model")
        usage = msg.get("usage")
        mid = msg.get("id") or record.get("requestId")
        if not usage or not mid or not model or model in _SKIP_MODELS:
            return out
        cc = usage.get("cache_creation") or {}
        cw_total = int(usage.get("cache_creation_input_tokens") or 0)
        cw_1h = int(cc.get("ephemeral_1h_input_tokens") or 0)
        # Older records lack the 5m/1h split: treat all cache writes as 5-minute writes.
        cw_5m = int(cc.get("ephemeral_5m_input_tokens") or 0) if cc else cw_total
        if cc and cw_5m + cw_1h < cw_total:
            cw_5m = cw_total - cw_1h
        stu = usage.get("server_tool_use") or {}
        out.usage = Usage(
            message_id=mid,
            session_id=session_id,
            ts=ts,
            model=model,
            is_sidechain=bool(record.get("isSidechain")),
            agent_id=record.get("agentId"),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_write_5m=cw_5m,
            cache_write_1h=cw_1h,
            cache_read=int(usage.get("cache_read_input_tokens") or 0),
            web_search_requests=int(stu.get("web_search_requests") or 0),
            service_tier=usage.get("service_tier"),
            tools=[
                ToolUse(id=b["id"], name=b.get("name", "?"), target=tool_target(b.get("name", ""), b.get("input")))
                for b in (msg.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
            ],
        )
    return out


def parse_line(line: str) -> Parsed | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    return parse_record(record)


# Record fields the parser reads; everything else (file contents, model output, thinking,
# system prompts, environment) is dropped before a record leaves the machine.
_KEEP_TOP = ("type", "subtype", "sessionId", "uuid", "parentUuid", "timestamp", "cwd", "gitBranch", "version",
             "entrypoint", "permissionMode", "isSidechain", "agentId", "isMeta", "isCompactSummary",
             "isVisibleInTranscriptOnly", "aiTitle", "requestId")


def slim_record(record: dict) -> dict | None:
    """Minimal, redacted copy of a transcript record for `wamt agent` to send to a server.

    Returns None for records the parser ignores. The server parses the result with the same
    parse_record(), so totals match a local scan exactly.
    """
    parsed = parse_record(record)
    if not (parsed.meta or parsed.prompt or parsed.usage or parsed.results or parsed.event):
        return None
    out = {k: record[k] for k in _KEEP_TOP if k in record}
    origin = record.get("origin") or {}
    if origin.get("kind"):
        out["origin"] = {"kind": origin["kind"]}
    if record.get("type") == "system" and record.get("compactMetadata"):
        cm = record["compactMetadata"]
        out["compactMetadata"] = {"trigger": cm.get("trigger"), "preTokens": cm.get("preTokens")}
    msg = record.get("message") or {}
    if record.get("type") == "assistant" and parsed.usage:
        out["message"] = {
            "id": msg.get("id"), "model": msg.get("model"), "role": "assistant", "usage": msg.get("usage"),
            "content": [{"type": "tool_use", "id": t.id, "name": t.name, "input": {"command": t.target}}
                        for t in parsed.usage.tools],
        }
    elif record.get("type") == "user":
        content = []
        if parsed.prompt:
            content.append({"type": "text", "text": parsed.prompt.text})
        elif parsed.event and parsed.event.kind == "command":
            name, _, args = (parsed.event.cause or "").partition(" ")
            content.append({"type": "text", "text": f"<command-name>{name}</command-name>"
                                                    f"<command-args>{args}</command-args>"})
        content += [{"type": "tool_result", "tool_use_id": r.tool_use_id, "is_error": r.is_error,
                     "content": {"chars": r.chars}} for r in parsed.results]
        out["message"] = {"role": "user", "content": content}
    return out
