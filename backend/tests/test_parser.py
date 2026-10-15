from wamt.collector.ingest import slugify
from wamt.collector.parser import parse_record

BASE = {"sessionId": "s", "uuid": "u", "timestamp": "2026-09-01T10:00:00Z", "type": "user"}


def prompt(content, **extra):
    return parse_record({**BASE, **extra, "message": {"role": "user", "content": content}}).prompt


def test_strips_ide_context_from_prompt():
    p = prompt([{"type": "text", "text": "<ide_opened_file>The user opened a.py</ide_opened_file>"},
                {"type": "text", "text": "Explain this"}])
    assert p.text == "Explain this"


def test_ide_context_only_is_not_a_prompt():
    assert prompt("<ide_selection>x = 1</ide_selection>") is None


def test_harness_messages_are_not_prompts():
    assert prompt("hi", isMeta=True) is None
    assert prompt("summary", isCompactSummary=True) is None
    assert prompt("<task-notification>done</task-notification>") is None
    assert prompt("report", origin={"kind": "peer"}) is None
    assert prompt([{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]) is None
    assert prompt("hello", origin={"kind": "human"}).text == "hello"


def test_cache_write_without_ttl_split_counts_as_5m():
    u = parse_record({**BASE, "type": "assistant", "message": {
        "id": "m", "model": "claude-sonnet-5",
        "usage": {"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 300}}}).usage
    assert (u.cache_write_5m, u.cache_write_1h) == (300, 0)


def test_slugify_matches_claude_project_dirs():
    assert slugify(r"c:\Users\dev\code\my_app") == "c--Users-dev-code-my-app"
