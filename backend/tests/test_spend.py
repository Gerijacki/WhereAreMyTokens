"""Plan value, budgets (API, states, alerts) and realized savings of insights marked done."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_insights import ROOT, SLUG, Transcript, bash

from wamt import alerts
from wamt.analytics.spend import budget_status, period_bounds
from wamt.collector.ingest import scan
from wamt.config import get_settings
from wamt.db import ApiCall, Budget, ChatSession, Insight, Project, init_engine, new_session
from wamt.insights.engine import refresh


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setenv("WAMT_INGEST_ENABLED", "false")
    monkeypatch.setenv("WAMT_PLAN", "max5x")
    get_settings.cache_clear()
    init_engine(f"sqlite:///{tmp_path / 'spend.db'}")
    with new_session() as s:
        s.add_all([Project(id=1, slug="shop", name="shop"), Project(id=2, slug="blog", name="blog")])
        s.add_all([ChatSession(id="s1", project_id=1, source="test"), ChatSession(id="s2", project_id=2, source="test")])
        s.commit()
    yield
    get_settings.cache_clear()


def add_calls(*calls: tuple[datetime, float, str]) -> None:
    with new_session() as s:
        for n, (ts, usd, session) in enumerate(calls):
            s.add(ApiCall(id=f"c{ts.timestamp()}-{n}", session_id=session, ts=ts, model="claude-opus-5-5",
                          cost_usd=usd))
        s.commit()


def client() -> TestClient:
    from wamt.main import app

    return TestClient(app)


# --------------------------------------------------------------------------- plan value

def test_plan_value_scales_short_history_to_a_month(db):
    now = datetime.now(UTC)
    add_calls(*((now - timedelta(days=d), 1.0, "s1") for d in range(1, 11)))  # $10 over the last 10 days
    data = client().get("/api/plan?months=3").json()

    assert data["current_plan"] == "max5x"
    assert data["trailing_30d_usd"] == pytest.approx(10.0)
    assert data["history_days"] == pytest.approx(10.0, abs=0.1)
    assert data["monthly_usd"] == pytest.approx(30.0, rel=0.02)  # 10 days of history scaled to 30
    plans = {p["id"]: p for p in data["plans"]}
    assert [p["id"] for p in data["plans"]] == ["pro", "max5x", "max20x"]  # cheapest first
    assert plans["pro"]["value_multiple"] == pytest.approx(1.5, rel=0.02) and not plans["pro"]["api_cheaper"]
    assert plans["max5x"]["api_cheaper"]
    assert len(data["months"]) == 3 and data["months"][-1]["partial"]
    assert sum(m["cost_usd"] for m in data["months"]) == pytest.approx(10.0)


def test_plan_value_without_history(db):
    data = client().get("/api/plan").json()
    assert data["monthly_usd"] == 0 and all(p["api_cheaper"] for p in data["plans"])


# --------------------------------------------------------------------------- budgets

def test_period_bounds():
    tz = ZoneInfo("Europe/Madrid")
    now = datetime(2026, 10, 15, 13, 30, tzinfo=tz)  # a Thursday
    assert period_bounds("day", now) == (datetime(2026, 10, 15, tzinfo=tz), datetime(2026, 10, 16, tzinfo=tz))
    assert period_bounds("week", now) == (datetime(2026, 10, 12, tzinfo=tz), datetime(2026, 10, 19, tzinfo=tz))
    assert period_bounds("month", datetime(2026, 12, 31, 23, tzinfo=tz)) == (
        datetime(2026, 12, 1, tzinfo=tz), datetime(2027, 1, 1, tzinfo=tz))


def test_budget_states_and_projection(db):
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)  # half of the day has elapsed
    add_calls((now - timedelta(hours=2), 4.0, "s1"), (now - timedelta(hours=1), 1.0, "s2"))
    with new_session() as s:
        ok, warn, over, shop = (Budget(period="day", limit_usd=v, project_id=p, created_at=now)
                                for v, p in ((20.0, None), (9.0, None), (5.0, None), (3.0, 1)))
        s.add_all([ok, warn, over, shop])
        s.commit()
        st = {b.id: budget_status(s, b, now) for b in (ok, warn, over, shop)}
    assert st[ok.id]["spent_usd"] == 5.0 and st[ok.id]["projected_usd"] == pytest.approx(10.0)
    assert st[ok.id]["state"] == "ok"
    assert st[warn.id]["state"] == "warning"  # 56% spent but heading for $10
    assert st[over.id]["state"] == "over" and st[over.id]["ratio"] == 1.0
    assert st[shop.id]["spent_usd"] == 4.0 and st[shop.id]["project"] == "shop"


def test_budget_api_crud(db):
    c = client()
    add_calls((datetime.now(UTC) - timedelta(seconds=5), 2.5, "s1"))
    created = c.post("/api/budgets", json={"period": "month", "limit_usd": 10, "project_id": 1})
    assert created.status_code == 201
    b = created.json()
    assert b["spent_usd"] == 2.5 and b["project"] == "shop"
    assert c.post("/api/budgets", json={"period": "year", "limit_usd": 10}).status_code == 422
    assert c.post("/api/budgets", json={"period": "day", "limit_usd": 0}).status_code == 422
    assert c.post("/api/budgets", json={"period": "day", "limit_usd": 5, "project_id": 99}).status_code == 422
    assert [i["id"] for i in c.get("/api/budgets").json()["items"]] == [b["id"]]
    assert c.delete(f"/api/budgets/{b['id']}").status_code == 200
    assert c.delete(f"/api/budgets/{b['id']}").status_code == 404
    assert c.get("/api/budgets").json()["items"] == []


def test_budget_alerts_fire_once_per_level(db, monkeypatch):
    monkeypatch.setenv("WAMT_ALERT_URL", "https://ntfy.example.com/wamt")
    get_settings.cache_clear()
    sent: list[str] = []
    monkeypatch.setattr(alerts, "send", lambda title, message, url=None: sent.append(title))
    c = client()
    c.post("/api/budgets", json={"period": "month", "limit_usd": 10})
    now = datetime.now(UTC)

    def budget_alerts():
        sent.clear()
        alerts.check(force=True)
        return [t for t in sent if "budget" in t]

    add_calls((now - timedelta(seconds=2), 8.5, "s1"))
    assert budget_alerts() == ["Month budget at 80%"]
    assert budget_alerts() == []
    add_calls((now - timedelta(seconds=1), 2.0, "s1"))
    assert budget_alerts() == ["Month budget exceeded"]
    assert budget_alerts() == []


# --------------------------------------------------------------------------- realized savings

@pytest.fixture
def savings(tmp_path):
    """A fix loop 30 days ago, then a week of ordinary work without it."""
    root = tmp_path / "projects"
    (root / SLUG).mkdir(parents=True)
    now = datetime.now(UTC)
    for s in range(4):
        t = Transcript(f"loop{s}", now - timedelta(days=30 - s))
        t.prompt("Make the cart tests pass")
        for _ in range(4):
            t.call([bash("pnpm test:run")], results=["FAIL cart.test.ts"])
            t.call([("Edit", {"file_path": ROOT + r"\src\cart.ts"})])
        t.call()
        (root / SLUG / f"loop{s}.jsonl").write_text("\n".join(t.lines) + "\n", encoding="utf-8")
    for s in range(3):
        t = Transcript(f"calm{s}", now - timedelta(days=6 - s))
        t.prompt(f"Add a discount code field to checkout step {s}")
        for _ in range(6):
            t.call([("Edit", {"file_path": ROOT + rf"\src\checkout{s}.ts"})])
        t.call()
        (root / SLUG / f"calm{s}.jsonl").write_text("\n".join(t.lines) + "\n", encoding="utf-8")
    init_engine(f"sqlite:///{tmp_path / 'savings.db'}")
    scan(root, "test")
    refresh()
    from wamt.main import app

    return TestClient(app)


def test_realized_savings_after_a_week(savings):
    c = savings
    loop = next(i for i in c.get("/api/insights").json()["items"] if i["type"] == "fix_loop")
    assert c.patch(f"/api/insights/{loop['id']}", json={"status": "done"}).status_code == 200

    done = c.get("/api/insights?status=done").json()
    assert done["summary"]["measuring"] == 1 and done["items"][0]["realized_usd_month"] is None
    assert done["items"][0]["baseline_usd_month"] == loop["est_usd_month"]

    with new_session() as s:  # pretend it was marked done 10 days ago, before the calm week
        s.get(Insight, loop["id"]).done_at = datetime.now(UTC) - timedelta(days=10)
        s.commit()
    refresh()
    done = c.get("/api/insights?status=done").json()
    item = done["items"][0]
    assert item["residual_usd_month"] == 0  # the loop didn't come back
    assert 0 < item["realized_usd_month"] <= 3 * item["baseline_usd_month"]
    assert done["summary"]["realized_usd_month"] == pytest.approx(item["realized_usd_month"], abs=0.01)
    assert done["summary"]["measuring"] == 0

    assert c.patch(f"/api/insights/{loop['id']}", json={"status": "open"}).status_code == 200
    reopened = next(i for i in c.get("/api/insights?include_stale=true").json()["items"] if i["id"] == loop["id"])
    assert reopened["done_at"] is None and reopened["realized_usd_month"] is None
