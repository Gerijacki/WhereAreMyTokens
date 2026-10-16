"""Settings: display preferences, dashboard password from the UI, devices and exports."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from wamt import auth
from wamt.config import get_settings
from wamt.db import ApiCall, ChatSession, Project, Turn, init_engine, new_session


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
    init_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    yield set_env
    get_settings.cache_clear()
    auth.secret_key.cache_clear()
    auth.stored_hash.cache_clear()


def client() -> TestClient:
    from wamt.main import app

    return TestClient(app)


def seed() -> None:
    now = datetime.now(UTC)
    with new_session() as s:
        s.add_all([Project(id=1, slug="shop", name="shop"), Project(id=2, slug="blog", name="blog")])
        s.add_all([ChatSession(id="s1", project_id=1, source="t", title="Cart", started_at=now - timedelta(days=2),
                               ended_at=now - timedelta(days=2)),
                   ChatSession(id="s2", project_id=2, source="t", title="Posts", started_at=now - timedelta(days=40),
                               ended_at=now - timedelta(days=40))])
        s.add_all([Turn(id="t1", session_id="s1", ts=now - timedelta(days=2), prompt="fix, the \"cart\"",
                        category="debugging"),
                   Turn(id="t2", session_id="s2", ts=now - timedelta(days=40), prompt="write a post", category="docs")])
        s.add_all([ApiCall(id="a1", session_id="s1", turn_id="t1", ts=now - timedelta(days=2), model="claude-opus-5-5",
                           input_tokens=10, output_tokens=200, cache_read=1000, cost_usd=1.5),
                   ApiCall(id="a2", session_id="s1", turn_id="t1", ts=now - timedelta(days=2), model="claude-opus-5-5",
                           output_tokens=100, cost_usd=0.5),
                   ApiCall(id="a3", session_id="s2", turn_id="t2", ts=now - timedelta(days=40),
                           model="claude-haiku-5-5", output_tokens=50, cost_usd=0.25)])
        s.commit()


# --------------------------------------------------------------------------- preferences

def test_preferences_defaults_saved_values_and_env_locks(env):
    c = client()
    s = c.get("/api/settings").json()
    assert (s["currency"], s["billing"], s["plan"], s["locked"]) == ("EUR", "monthly", None, [])

    s = c.patch("/api/settings", json={"currency": "usd", "plan": "pro", "billing": "annual"}).json()
    assert (s["currency"], s["plan"], s["billing"]) == ("USD", "pro", "annual")
    assert c.get("/api/settings").json()["plan"] == "pro"  # persisted
    for bad in ({"currency": "GBP"}, {"eur_per_usd": 0}, {"billing": "weekly"}, {"plan": "ultra"}, {"theme": "x"}):
        assert c.patch("/api/settings", json=bad).status_code == 422, bad

    env(currency="EUR", eur_per_usd="0.9")
    s = c.get("/api/settings").json()
    assert s["currency"] == "EUR" and s["eur_per_usd"] == 0.9 and s["plan"] == "pro"  # env wins, the rest stays
    assert s["locked"] == ["currency", "eur_per_usd"]
    r = c.patch("/api/settings", json={"currency": "USD"})
    assert r.status_code == 409 and "WAMT_CURRENCY" in r.json()["detail"]


def test_plan_value_in_euros_and_annual_billing(env):
    seed()
    c = client()
    c.patch("/api/settings", json={"currency": "EUR", "eur_per_usd": 0.8, "billing": "annual", "plan": "pro"})
    data = c.get("/api/plan").json()
    pro = next(p for p in data["plans"] if p["id"] == "pro")
    assert (pro["price"], pro["price_currency"]) == (15.0, "EUR")
    assert pro["usd_month"] == pytest.approx(15 / 0.8)  # served in USD, converted back by the dashboard
    assert data["current_plan"] == "pro" and data["billing"] == "annual"


# --------------------------------------------------------------------------- password from the UI

def test_password_set_change_and_remove_from_the_ui(env):
    a, b = client(), client()
    assert a.get("/api/auth/status").json()["source"] == "none"
    assert a.put("/api/auth/password", json={"new": "short"}).status_code == 422
    assert a.put("/api/auth/password", json={"new": "first-password"}).status_code == 200
    assert a.get("/api/overview").status_code == 200  # the browser that set it stays signed in
    assert b.get("/api/overview").status_code == 401
    assert b.get("/api/auth/status").json() == {"required": True, "authenticated": False, "source": "ui",
                                                "proxy_header": None}
    assert b.post("/api/auth/login", json={"password": "first-password"}).status_code == 200
    assert b.get("/api/overview").status_code == 200

    assert a.put("/api/auth/password", json={"current": "nope", "new": "second-password"}).status_code == 403
    assert a.put("/api/auth/password", json={"current": "first-password", "new": "second-password"}).status_code == 200
    assert a.get("/api/overview").status_code == 200
    assert b.get("/api/overview").status_code == 401  # changing the password signed the other browser out
    assert b.post("/api/auth/login", json={"password": "first-password"}).status_code == 401

    assert a.request("DELETE", "/api/auth/password", json={"current": "wrong-password"}).status_code == 403
    assert a.request("DELETE", "/api/auth/password", json={"current": "second-password"}).status_code == 200
    assert b.get("/api/overview").status_code == 200  # open again
    assert a.request("DELETE", "/api/auth/password", json={"current": "x"}).status_code == 404


def test_env_password_cannot_be_changed_from_the_ui(env):
    env(auth_password="from-the-env")
    c = client()
    c.post("/api/auth/login", json={"password": "from-the-env"})
    assert c.put("/api/auth/password", json={"current": "from-the-env", "new": "something-else"}).status_code == 409
    assert c.request("DELETE", "/api/auth/password", json={"current": "from-the-env"}).status_code == 409


def test_stranger_cannot_change_a_ui_password(env):
    owner, stranger = client(), client()
    owner.put("/api/auth/password", json={"new": "owner-password"})
    assert stranger.put("/api/auth/password", json={"new": "taken-over"}).status_code == 403
    assert stranger.put("/api/auth/password", json={"current": "owner-password", "new": "taken-over"}).status_code == 403
    assert stranger.get("/api/settings").status_code == 401


# --------------------------------------------------------------------------- devices

def test_devices_from_the_ui(env):
    c = client()
    created = c.post("/api/devices", json={"name": "work-laptop"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("wamt_")
    assert c.post("/api/devices", json={"name": "work-laptop"}).status_code == 409
    assert c.post("/api/devices", json={"name": "bad name!"}).status_code == 422
    listed = c.get("/api/devices").json()
    assert [d["name"] for d in listed] == ["work-laptop"] and "token" not in listed[0]

    push = {"files": [{"path": "proj/s.jsonl", "records": []}]}
    headers = {"Authorization": f"Bearer {token}"}
    assert c.post("/api/ingest", json=push, headers=headers).status_code == 200
    assert c.delete("/api/devices/work-laptop").status_code == 200
    assert c.get("/api/devices").json()[0]["revoked"] is True
    assert c.post("/api/ingest", json=push, headers=headers).status_code == 401
    assert c.delete("/api/devices/nope").status_code == 404


# --------------------------------------------------------------------------- exports

def test_exports(env):
    seed()
    c = client()
    c.patch("/api/settings", json={"currency": "EUR", "eur_per_usd": 0.5})

    r = c.get("/api/export/sessions.csv?days=30")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="wamt-sessions-30d.csv"' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [(x["session_id"], x["api_calls"], x["cost_usd"], x["cost_eur"]) for x in rows] == [("s1", "2", "2.0", "1.0")]

    prompts = c.get("/api/export/prompts.json?days=0").json()
    assert [p["prompt"] for p in prompts] == ["write a post", 'fix, the "cart"']
    assert prompts[1]["output_tokens"] == 300

    daily = list(csv.DictReader(io.StringIO(c.get("/api/export/daily.csv?days=0&project_id=2").text)))
    assert [(d["project"], d["model"], d["cost_usd"]) for d in daily] == [("blog", "claude-haiku-5-5", "0.25")]

    c.patch("/api/settings", json={"currency": "USD"})
    assert "cost_eur" not in c.get("/api/export/sessions.json?days=0").json()[0]
    assert c.get("/api/export/tools.csv").status_code == 404
    assert c.get("/api/export/sessions.xml").status_code == 404
