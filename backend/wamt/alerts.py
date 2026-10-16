"""Push alerts to ntfy, Discord, Slack or any JSON webhook (WAMT_ALERT_URL).

Rules (each fires once, remembered in the `meta` table):
- the current 5-hour block is projected above WAMT_ALERT_BLOCK_FACTOR x your median block;
- a new high-impact insight appears;
- a budget reaches 80% of its limit, then again when it is exceeded (once per budget period);
- a daily digest at WAMT_ALERT_DIGEST_HOUR (local time), if set.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from wamt.analytics.blocks import compute_limits
from wamt.analytics.spend import WARN_RATIO, all_budgets
from wamt.config import get_settings
from wamt.db import ApiCall, Insight, get_meta, new_session, set_meta

log = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 60
_last_check = 0.0


def send(title: str, message: str, url: str | None = None) -> None:
    url = url or get_settings().alert_url
    if not url:
        return
    link = get_settings().public_url
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        body, headers = {"content": f"**{title}**\n{message}"}, {"Content-Type": "application/json"}
    elif "hooks.slack.com" in url:
        body, headers = {"text": f"*{title}*\n{message}"}, {"Content-Type": "application/json"}
    elif "ntfy" in url:
        headers = {"Title": title.encode("ascii", "replace").decode(), "Tags": "chart_with_upwards_trend"}
        if link:
            headers["Click"] = link
        req = urllib.request.Request(url, data=message.encode(), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        return
    else:
        body = {"title": title, "message": message, "url": link}
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def _usd(v: float) -> str:
    """Format an amount (stored in USD) in the display currency."""
    from wamt.preferences import money

    with new_session() as db:
        return money(db, v)


def check(force: bool = False) -> list[str]:
    """Evaluate the rules and send what fired. Returns the titles sent (useful for tests)."""
    global _last_check
    s = get_settings()
    if not s.alert_url or (not force and time.monotonic() - _last_check < CHECK_EVERY_SECONDS):
        return []
    _last_check = time.monotonic()
    sent: list[str] = []
    with new_session() as db:
        # 1. Heavy 5-hour block
        lim = compute_limits(db, days=30)
        cur, median = lim["current"], lim["median_block_cost_usd"]
        if cur and median > 0 and cur["projected_cost_usd"] > s.alert_block_factor * median:
            key = str(cur["start"])
            if get_meta(db, "alert_block") != key:
                title = "Heavy usage block"
                send(title, f"This 5-hour block is heading for {_usd(cur['projected_cost_usd'])} (API-equivalent), "
                            f"{cur['projected_cost_usd'] / median:.1f}x your median block. "
                            f"Burn rate {_usd(cur['burn_usd_per_hour'])}/h, {cur['minutes_left']} min left.")
                set_meta(db, "alert_block", key)
                sent.append(title)

        # 2. New high-impact insights
        known = set(json.loads(get_meta(db, "alert_insights") or "[]"))
        fresh = db.scalars(select(Insight).where(Insight.severity == "high", Insight.status == "open",
                                                 Insight.stale.is_(False))).all()
        new = [i for i in fresh if i.id not in known]
        if new:
            title = "New savings opportunity" if len(new) == 1 else f"{len(new)} new savings opportunities"
            send(title, "\n".join(f"- {i.title} (~{_usd(i.est_usd_month)}/mo)" for i in new))
            sent.append(title)
            set_meta(db, "alert_insights", json.dumps(sorted(known | {i.id for i in new})))

        # 3. Budgets: one alert per level (warning, then over) and budget period
        for b in all_budgets(db):
            level = "over" if b["state"] == "over" else "warning" if b["ratio"] >= WARN_RATIO else None
            key, meta = f"{b['period_start'].isoformat()}|{level}", f"alert_budget_{b['id']}"
            if level is None or get_meta(db, meta) in (key, f"{b['period_start'].isoformat()}|over"):
                continue
            scope = f" for {b['project']}" if b["project"] else ""
            title = f"{b['period'].capitalize()} budget{scope} " + ("exceeded" if level == "over" else "at 80%")
            send(title, f"{_usd(b['spent_usd'])} of {_usd(b['limit_usd'])} spent this {b['period']} "
                        f"(API-equivalent){scope}.")
            set_meta(db, meta, key)
            sent.append(title)

        # 4. Daily digest
        if s.alert_digest_hour is not None:
            now = datetime.now(ZoneInfo(s.timezone))
            today = now.date().isoformat()
            if now.hour >= s.alert_digest_hour and get_meta(db, "alert_digest") != today:
                start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                cost, calls = db.execute(select(func.coalesce(func.sum(ApiCall.cost_usd), 0.0), func.count(ApiCall.id))
                                         .where(ApiCall.ts >= start, ApiCall.ts < end)).one()
                open_usd = db.scalar(select(func.coalesce(func.sum(Insight.est_usd_month), 0.0))
                                     .where(Insight.status == "open", Insight.stale.is_(False))) or 0.0
                title = f"Claude Code yesterday: {_usd(cost)}"
                send(title, f"{calls:,} API calls, {_usd(cost)} API-equivalent. "
                            f"Open insights could save ~{_usd(open_usd)}/mo.")
                set_meta(db, "alert_digest", today)
                sent.append(title)
        db.commit()
    return sent


def check_safely() -> None:
    try:
        check()
    except Exception:
        log.exception("Alert check failed")
