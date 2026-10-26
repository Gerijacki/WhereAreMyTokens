"""Self-hosting features: redaction, agent/device ingest, auth, OTLP, Prometheus, alerts, migrations, demo."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text

from wamt import alerts, auth
from wamt.agent import Agent
from wamt.collector.ingest import scan
from wamt.collector.parser import parse_record, slim_record
from wamt.collector.redact import redact
from wamt.config import get_settings
from wamt.db import ApiCall, Base, OtelPoint, ToolCall, Turn, init_engine, new_session

FIXTURES = Path(__file__).parent / "fixtures" / "projects"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolated DB + settings; returns a function to set WAMT_* env vars."""
    def set_env(**values):
        for k, v in values.items():
            monkeypatch.setenv(f"WAMT_{k.upper()}", str(v))
        get_settings.cache_clear()
        auth.secret_key.cache_clear()
        auth.stored_hash.cache_clear()

    monkeypatch.setenv("WAMT_INGEST_ENABLED", "false")
    set_env()
    init_engine(f"sqlite:///{tmp_path / 'm4.db'}")
    yield set_env
    get_settings.cache_clear()
    auth.secret_key.cache_clear()
    auth.stored_hash.cache_clear()


def client():
    from wamt.main import app

    return TestClient(app)


def test_redaction_masks_secrets_and_emails():
    cases = [
        "export ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        'curl -H "Authorization: Bearer abcdef1234567890abcdef" https://api.example.com',
        "git remote add origin https://user:hunter2secret@github.com/me/repo.git",
        "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "DATABASE_PASSWORD=supersecret psql",
        "mail me at jane.doe@example.com",
        "aws AKIAABCDEFGHIJKLMNOP",
    ]
    for c in cases:
        out = redact(c)
        assert "[REDACTED]" in out or "[EMAIL]" in out, c
    for leaked in ("sk-ant-api03", "hunter2secret", "ghp_abc", "supersecret", "jane.doe", "AKIAABCD"):
        assert all(leaked not in redact(c) for c in cases)
    assert redact("pnpm test -- src/cart") == "pnpm test -- src/cart"


def test_prompts_and_commands_are_redacted_on_ingest(env):
    rec = {"sessionId": "s", "uuid": "u", "timestamp": "2026-09-01T10:00:00Z", "type": "user",
           "message": {"role": "user", "content": "deploy with key sk-ant-api03-zzzzzzzzzzzzzzzzzzzz please"}}
    assert "sk-ant" not in parse_record(rec).prompt.text


def test_slim_record_drops_content_but_keeps_totals():
    lines = (FIXTURES / "C--demo-app" / "s1.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        rec = json.loads(line)
        slim = slim_record(rec)
        if slim is None:
            continue
        dumped = json.dumps(slim)
        assert "FAIL login.test.ts" not in dumped and "Running the tests." not in dumped
        full, small = parse_record(rec), parse_record(slim)
        if full.usage:
            assert (full.usage.output_tokens, [t.target for t in full.usage.tools]) == \
                   (small.usage.output_tokens, [t.target for t in small.usage.tools])
        if full.prompt:
            assert full.prompt.text == small.prompt.text
        assert [(r.tool_use_id, r.chars, r.is_error) for r in full.results] == \
               [(r.tool_use_id, r.chars, r.is_error) for r in small.results]


def test_agent_pushes_to_server_with_device_token(env, tmp_path, monkeypatch):
    from wamt import devices

    with new_session() as db:
        token = devices.create(db, "laptop")
    c = client()
    assert c.post("/api/ingest", json={"files": []}, headers={"Authorization": "Bearer nope"}).status_code == 401

    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)

    def post(self, files):
        r = c.post("/api/ingest", json={"files": files}, headers={"Authorization": f"Bearer {self.token}"})
        assert r.status_code == 200, r.text

    monkeypatch.setattr(Agent, "_post", post)
    agent = Agent("http://test", token, root, tmp_path / "state.json")
    assert agent.sync_once() > 0
    assert agent.sync_once() == 0  # offsets persisted, nothing new
    with new_session() as db:
        assert db.scalar(select(func.sum(ApiCall.output_tokens))) == 160  # same totals as a local scan
        assert db.scalar(select(func.count(Turn.id))) == 2
        assert db.get(ToolCall, "tu1").is_error
        assert db.scalar(select(ApiCall.session_id).limit(1)) == "s1"
    with new_session() as db:
        devices.revoke(db, "laptop")
    assert c.post("/api/ingest", json={"files": []}, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_agent_queues_while_offline_and_survives_deleted_transcripts(env, tmp_path, monkeypatch):
    import urllib.error

    from wamt import devices

    with new_session() as db:
        token = devices.create(db, "laptop")
    c = client()
    online = False

    def post(self, files):
        if not online:
            raise urllib.error.URLError("homelab unreachable")
        r = c.post("/api/ingest", json={"files": files}, headers={"Authorization": f"Bearer {self.token}"})
        assert r.status_code == 200, r.text

    monkeypatch.setattr(Agent, "_post", post)
    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)
    agent = Agent("http://test", token, root, tmp_path / "state" / "state.json")
    agent.run(once=True)  # offline: logged, not raised
    assert agent.pending()

    shutil.rmtree(root)  # Claude Code cleaned up old transcripts meanwhile
    root.mkdir()
    restarted = Agent("http://test", token, root, tmp_path / "state" / "state.json")
    online = True
    assert restarted.sync_once() > 0
    assert restarted.pending() == []
    with new_session() as db:
        assert db.scalar(select(func.sum(ApiCall.output_tokens))) == 160
        assert db.scalar(select(func.count(Turn.id))) == 2


def test_store_prompts_off_keeps_length_and_category(env, tmp_path):
    env(store_prompts="false")
    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)
    scan(root, "test")
    with new_session() as db:
        turns = db.scalars(select(Turn).order_by(Turn.ts)).all()
        assert [t.prompt for t in turns] == [None, None]
        assert turns[0].prompt_chars == len("Fix the failing login test")
        assert turns[0].category == "debugging"  # classified from the in-memory text


def test_password_auth(env):
    env(auth_password="s3cret")
    c = client()
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/auth/status").json() == {"required": True, "authenticated": False, "source": "env",
                                                 "proxy_header": None}
    assert c.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"password": "s3cret"}).status_code == 200
    assert c.get("/api/overview").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/overview").status_code == 401


def test_proxy_header_auth(env):
    env(auth_password="x", trust_proxy_auth_header="Remote-User")
    c = client()
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Remote-User": "alice"}).status_code == 200


def _otlp_value(v):
    return {"intValue": str(v)} if isinstance(v, int) else {"stringValue": v}


def test_otlp_logs_and_metrics(env):
    c = client()
    attrs = {"event.name": "api_request", "model": "claude-sonnet-5-5", "cost_usd": "0.012", "input_tokens": 10,
             "output_tokens": 200, "cache_read_tokens": 5000, "cache_creation_tokens": 300,
             "session.id": "abc", "user.email": "someone@example.com"}
    logs = {"resourceLogs": [{"resource": {"attributes": []}, "scopeLogs": [{"logRecords": [{
        "timeUnixNano": "1760000000000000000", "body": {"stringValue": "claude_code.api_request"},
        "attributes": [{"key": k, "value": _otlp_value(v)} for k, v in attrs.items()]}]}]}]}
    assert c.post("/v1/logs", json=logs).json()["accepted"] == 1
    metrics = {"resourceMetrics": [{"scopeMetrics": [{"metrics": [{"name": "claude_code.token.usage", "sum": {
        "dataPoints": [{"asInt": "1234", "timeUnixNano": "1760000000000000000",
                        "attributes": [{"key": "type", "value": {"stringValue": "cacheRead"}}]}]}}]}]}]}
    assert c.post("/v1/metrics", json=metrics).json()["accepted"] == 1
    assert c.post("/v1/metrics", content=b"\x00", headers={"content-type": "application/x-protobuf"}).status_code == 415
    with new_session() as db:
        ev = db.scalar(select(OtelPoint).where(OtelPoint.kind == "event"))
        assert (ev.model, ev.output_tokens, ev.cache_read, ev.value) == ("claude-sonnet-5-5", 200, 5000, 0.012)
        assert "someone@example.com" not in ev.attrs
    t = c.get("/api/telemetry?days=0").json()
    assert t["active"] and t["by_source_model"][0]["requests"] == 1


def test_prometheus_metrics(env, tmp_path):
    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)
    scan(root, "test")
    body = client().get("/metrics").text
    assert '# TYPE wamt_tokens_total counter' in body
    assert 'wamt_tokens_total{model="claude-sonnet-5",kind="output"} 120' in body
    env(metrics_token="m")
    assert client().get("/metrics").status_code == 401
    assert client().get("/metrics", headers={"Authorization": "Bearer m"}).status_code == 200


def test_alerts_fire_once(env, tmp_path, monkeypatch):
    from wamt.insights.engine import refresh

    env(alert_url="https://ntfy.example.com/topic")
    sent = []
    monkeypatch.setattr(alerts, "send", lambda title, message, url=None: sent.append(title))
    from wamt.demo import generate

    generate(tmp_path / "demo", days=20, seed=3)
    scan(tmp_path / "demo", "demo")
    refresh()
    with new_session() as db:
        from wamt.db import Insight

        db.scalars(select(Insight)).first().severity = "high"
        db.commit()
    first = alerts.check(force=True)
    assert any("savings" in t for t in first)
    assert not any("savings" in t for t in alerts.check(force=True))  # already notified


def test_demo_data_triggers_every_dashboard(env, tmp_path):
    from wamt.demo import generate
    from wamt.insights.engine import refresh

    assert generate(tmp_path / "demo", days=30, seed=7) > 20
    scan(tmp_path / "demo", "demo")
    refresh()
    c = client()
    types = {i["type"] for i in c.get("/api/insights").json()["items"]}
    assert {"file_rereads", "cache_rebuild", "context_bloat", "fix_loop", "command_sequence", "model_fit",
            "large_context", "repeated_prompt", "allowlist"} <= types
    assert c.get("/api/limits?days=7").json()["current"] is not None  # a block is in progress
    cats = {r["category"] for r in c.get("/api/categories?days=0").json()["by_category"]}
    assert {"coding", "debugging", "ops", "exploration"} <= cats


def test_pre_alembic_database_is_stamped_and_upgraded(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    eng = create_engine(url)
    legacy = [Base.metadata.tables[n] for n in ("projects", "sessions", "turns", "api_calls", "tool_calls")]
    Base.metadata.create_all(eng, tables=legacy)
    with eng.begin() as conn:  # an M1-era table without the later columns
        conn.execute(text("DROP INDEX ix_tool_calls_signature"))
        conn.execute(text("ALTER TABLE tool_calls DROP COLUMN signature"))
    init_engine(url)
    insp = inspect(create_engine(url))
    assert {"devices", "otel_points", "insights", "alembic_version"} <= set(insp.get_table_names())
    assert "signature" in {c["name"] for c in insp.get_columns("tool_calls")}
