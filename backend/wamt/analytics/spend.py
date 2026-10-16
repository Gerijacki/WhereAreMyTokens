"""Plan value and budgets: API-equivalent spend compared with what you pay, or allow yourself to spend.

Both are price comparisons. Claude plans don't publish their usage limits in tokens, so the plan
view can say what your usage would cost on the API, not whether it would fit a smaller plan.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wamt.api.queries import day_bucket
from wamt.config import get_settings
from wamt.db import ApiCall, Budget, ChatSession, Project
from wamt.preferences import effective
from wamt.pricing import load_plans

PERIODS = ("day", "week", "month")
WARN_RATIO = 0.8  # a budget turns "warning" at 80% spent, or when projected past its limit
MIN_PROJECTION_SHARE = 0.1  # don't project a period's spend before 10% of it has elapsed


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def spent(db: Session, start: datetime, end: datetime | None = None, project_id: int | None = None) -> float:
    stmt = select(func.coalesce(func.sum(ApiCall.cost_usd), 0.0)).where(ApiCall.ts >= start)
    if end is not None:
        stmt = stmt.where(ApiCall.ts < end)
    if project_id is not None:
        stmt = stmt.join(ChatSession, ChatSession.id == ApiCall.session_id).where(
            ChatSession.project_id == project_id)
    return float(db.scalar(stmt) or 0.0)


def _month_start(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(d: datetime) -> datetime:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


# --------------------------------------------------------------------------- plan value

def plan_value(db: Session, months: int = 6, now: datetime | None = None) -> dict:
    """API-equivalent cost per calendar month and over the last 30 days, against each plan's price.

    `monthly_usd` is the last 30 days of cost. With less than 30 days of history it is scaled up
    to 30 days, which assumes the days you have are typical.
    """
    tz = ZoneInfo(get_settings().timezone)
    now = (now or datetime.now(UTC)).astimezone(tz)
    plans = load_plans()

    trailing = spent(db, (now - timedelta(days=30)).astimezone(UTC))
    first_call = db.scalar(select(func.min(ApiCall.ts)))
    history_days = min(30.0, (now - _aware(first_call)).total_seconds() / 86400) if first_call else 0.0
    monthly = trailing * 30 / history_days if 0 < history_days < 30 else trailing

    first_month = _month_start(now)
    for _ in range(months - 1):
        first_month = _month_start(first_month - timedelta(days=1))
    day = day_bucket(db, ApiCall.ts).label("day")
    by_month: dict[str, float] = defaultdict(float)
    for r in db.execute(select(day, func.coalesce(func.sum(ApiCall.cost_usd), 0.0).label("cost"))
                        .where(ApiCall.ts >= first_month.astimezone(UTC)).group_by(day)).all():
        by_month[str(r.day)[:7]] += float(r.cost)

    month_rows = []
    m = first_month
    while m <= now:
        key = m.strftime("%Y-%m")
        cost = by_month.get(key, 0.0)
        row = {"month": key, "cost_usd": round(cost, 4), "partial": False, "projected_usd": None}
        if m == _month_start(now):
            elapsed = (now - m).total_seconds() / 86400
            days_in = calendar.monthrange(m.year, m.month)[1]
            row["partial"] = True
            row["projected_usd"] = round(cost * days_in / elapsed, 4) if elapsed >= 1 else None
        month_rows.append(row)
        m = _next_month(m)

    prefs = effective(db)
    out_plans = []
    for p in plans:
        price, cur = p.price(prefs["currency"], prefs["billing"])
        usd_month = price / prefs["eur_per_usd"] if cur == "EUR" else price  # amounts are served in USD
        out_plans.append({"id": p.id, "name": p.name, "price": price, "price_currency": cur,
                          "usd_month": round(usd_month, 4),
                          "value_multiple": round(monthly / usd_month, 2) if usd_month else None,
                          "api_cheaper": monthly < usd_month})
    return {
        "current_plan": prefs["plan"],
        "billing": prefs["billing"],
        "monthly_usd": round(monthly, 4),
        "trailing_30d_usd": round(trailing, 4),
        "history_days": round(history_days, 1),
        "plans": out_plans,
        "months": month_rows,
    }


# --------------------------------------------------------------------------- budgets

def period_bounds(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Start and end of the day, week (Monday first) or month containing `now`, in now's timezone."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return midnight, midnight + timedelta(days=1)
    if period == "week":
        start = midnight - timedelta(days=now.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = _month_start(now)
        return start, _next_month(start)
    raise ValueError(f"unknown budget period {period!r}")


def budget_status(db: Session, b: Budget, now: datetime | None = None,
                  projects: dict[int, str] | None = None) -> dict:
    """Spend so far in the budget's current period and a linear projection to the period's end."""
    tz = ZoneInfo(get_settings().timezone)
    now = (now or datetime.now(UTC)).astimezone(tz)
    start, end = period_bounds(b.period, now)
    used = spent(db, start.astimezone(UTC), end.astimezone(UTC), b.project_id)
    share = (now - start) / (end - start)
    projected = used / share if share >= MIN_PROJECTION_SHARE else None
    if used >= b.limit_usd:
        state = "over"
    elif used >= WARN_RATIO * b.limit_usd or (projected is not None and projected > b.limit_usd):
        state = "warning"
    else:
        state = "ok"
    if projects is None and b.project_id is not None:
        p = db.get(Project, b.project_id)
        projects = {p.id: p.name} if p else {}
    return {
        "id": b.id, "period": b.period, "limit_usd": b.limit_usd, "project_id": b.project_id,
        "project": (projects or {}).get(b.project_id) if b.project_id is not None else None,
        "period_start": start, "period_end": end, "spent_usd": round(used, 4),
        "ratio": round(used / b.limit_usd, 4) if b.limit_usd else None,
        "projected_usd": round(projected, 4) if projected is not None else None, "state": state,
    }


def all_budgets(db: Session, now: datetime | None = None) -> list[dict]:
    projects = dict(db.execute(select(Project.id, Project.name)).all())
    order = {p: i for i, p in enumerate(PERIODS)}
    rows = sorted(db.scalars(select(Budget)), key=lambda b: (b.project_id is not None, order[b.period], b.id))
    return [budget_status(db, b, now, projects) for b in rows]
