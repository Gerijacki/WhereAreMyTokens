import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from wamt.collector.ingest import scan
from wamt.db import ApiCall, ChatSession, Project, ToolCall, Turn, init_engine, new_session
from wamt.pricing import cost_usd

FIXTURES = Path(__file__).parent / "fixtures" / "projects"


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)
    init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    return root


def test_dedupes_usage_by_message_id(data_dir):
    scan(data_dir, "test")
    with new_session() as db:
        a = db.get(ApiCall, "msg_A")
        # Three lines share msg_A; usage must be counted once, keeping the final output count.
        assert (a.input_tokens, a.output_tokens, a.cache_write_5m, a.cache_read) == (10, 120, 1000, 0)
        assert db.scalar(select(func.count(ApiCall.id))) == 3  # A, B, C - synthetic skipped
        assert db.scalar(select(func.sum(ApiCall.output_tokens))) == 160


def test_cost_uses_pricing_table(data_dir):
    scan(data_dir, "test")
    with new_session() as db:
        a = db.get(ApiCall, "msg_A")
        # sonnet-5: $2 in, $10 out, 5m write 1.25x, per MTok
        assert a.cost_usd == pytest.approx((10 * 2 + 120 * 10 + 1000 * 2.5) / 1e6)
        c = db.get(ApiCall, "msg_C")
        # opus-5-5: 1h write is 2x input ($8), cache read $0.20
        assert c.cost_usd == pytest.approx((2 * 4 + 10 * 20 + 500 * 8 + 1000 * 0.2) / 1e6)
    assert cost_usd("unknown-model", 1, 1, 1, 1, 1) is None


def test_turns_prompts_and_tools(data_dir):
    scan(data_dir, "test")
    with new_session() as db:
        turns = db.scalars(select(Turn).order_by(Turn.ts)).all()
        assert [t.prompt for t in turns] == ["Fix the failing login test", "Now commit it"]
        assert db.get(ApiCall, "msg_A").turn_id == "p1"
        assert db.get(ApiCall, "msg_B").turn_id == "p1"  # subagent work belongs to the spawning turn
        assert db.get(ApiCall, "msg_B").is_sidechain
        assert db.get(ApiCall, "msg_C").turn_id == "p2"
        bash = db.get(ToolCall, "tu1")
        assert (bash.name, bash.target, bash.is_error) == ("Bash", "pnpm test", True)
        s = db.get(ChatSession, "s1")
        assert s.title == "Fix login test"
        assert s.git_branch == "main"
        assert db.scalar(select(Project.name)) == "app"


def test_incremental_scan_is_idempotent_and_picks_up_appends(data_dir):
    scan(data_dir, "test")
    assert scan(data_dir, "test") == 0
    f = data_dir / "C--demo-app" / "s1.jsonl"
    line = f.read_text(encoding="utf-8").splitlines()[-1].replace("msg_C", "msg_D").replace('"a6"', '"a7"')
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    assert scan(data_dir, "test") == 1
    with new_session() as db:
        assert db.scalar(select(func.count(ApiCall.id))) == 4


def test_partial_trailing_line_waits_for_newline(data_dir):
    f = data_dir / "C--demo-app" / "s1.jsonl"
    content = f.read_text(encoding="utf-8")
    f.write_text(content[:-40], encoding="utf-8")  # writer is mid-line
    scan(data_dir, "test")
    with new_session() as db:
        assert db.get(ApiCall, "msg_C") is None
    f.write_text(content, encoding="utf-8")
    scan(data_dir, "test")
    with new_session() as db:
        assert db.get(ApiCall, "msg_C") is not None


def test_api_endpoints(data_dir):
    scan(data_dir, "test")
    from wamt.main import app

    client = TestClient(app)
    ov = client.get("/api/overview?days=0").json()
    assert ov["totals"]["output_tokens"] == 160
    assert ov["totals"]["sessions"] == 1
    assert ov["totals"]["prompts"] == 2
    assert {m["model"] for m in ov["by_model"]} == {"claude-sonnet-5", "claude-haiku-4-5-20251001", "claude-opus-5-5"}
    assert ov["daily"][0]["day"] == "2026-09-01"

    sessions = client.get("/api/sessions?days=0").json()
    assert sessions[0]["id"] == "s1"
    detail = client.get("/api/sessions/s1").json()
    assert detail["turns"][0]["tools"] == {"Bash": 1, "Read": 1}
    # p2 (opus 1h cache write, $0.0044) outranks p1 (sonnet + haiku subagent, $0.0041)
    assert [t["id"] for t in client.get("/api/turns/top?days=0").json()] == ["p2", "p1"]
    assert client.get("/api/projects?days=0").json()[0]["name"] == "app"
