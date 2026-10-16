"""Run the miners and persist their findings, keeping each insight's status across refreshes."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wamt.analytics.spend import spent
from wamt.db import ApiCall, Insight, new_session, set_meta
from wamt.insights.data import Dataset, load
from wamt.insights.miners import MINERS, Finding

log = logging.getLogger(__name__)
REFRESH_SECONDS = 600
MIN_USD_MONTH = 0.10  # below this a finding is noise
MEASURE_AFTER_DAYS = 7  # realized savings need at least a week of data after an insight is marked done
MEASURE_STEP_DAYS = 7  # measurement windows are rounded down to whole weeks so datasets can be shared
MAX_ACTIVITY_FACTOR = 3.0
_last_refresh = 0.0


def _severity(f: Finding, monthly: float) -> str:
    if f.severity:
        return f.severity
    if monthly >= 20:
        return "high"
    if monthly >= 5:
        return "medium"
    return "low"


def insight_id(f: Finding) -> str:
    return hashlib.sha1(f"{f.type}|{f.key}".encode()).hexdigest()[:16]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _run_miners(ds: Dataset) -> dict[str, Finding]:
    findings: dict[str, Finding] = {}
    for miner in MINERS:
        try:
            for f in miner(ds):
                findings[insight_id(f)] = f
        except Exception:
            log.exception("Insight miner %s failed", miner.__name__)
    return findings


def measure_done(db: Session, days: int, now: datetime) -> int:
    """Realized savings of the insights marked done at least MEASURE_AFTER_DAYS ago.

    The miners run again on the data recorded since the insight was marked done (rounded down to
    whole weeks). Whatever is still found is the residual cost, scaled to 30 days. The baseline
    (est_usd_month when it was marked done) is first scaled by the activity factor: API-equivalent
    spend per day since then over spend per day in the analysis window before it, for the insight's
    project (or overall). That way working less doesn't count as savings:

        realized = max(0, baseline x activity_factor - residual)

    Assumptions: the drop is caused by the fix; a pattern that falls under a detector's threshold
    in the shorter window counts as gone. Returns the number of insights measured.
    """
    first_call = db.scalar(select(func.min(ApiCall.ts)))
    done = [i for i in db.scalars(select(Insight).where(Insight.status == "done", Insight.done_at.is_not(None)))
            if i.baseline_usd_month is not None]
    windows: dict[int, tuple[Dataset, dict[str, Finding]]] = {}
    measured = 0
    for i in done:
        done_at = _aware(i.done_at)
        elapsed = (now - done_at).total_seconds() / 86400
        if elapsed < MEASURE_AFTER_DAYS:
            i.residual_usd_month = i.realized_usd_month = i.measured_at = None
            continue
        window = min(int(elapsed // MEASURE_STEP_DAYS) * MEASURE_STEP_DAYS, days)
        if window not in windows:
            ds = load(db, window)
            windows[window] = (ds, _run_miners(ds))
        ds, findings = windows[window]
        f = findings.get(i.id)
        residual = f.est_usd * 30 / window if f else 0.0
        before_days = min(days, (done_at - _aware(first_call)).total_seconds() / 86400) if first_call else 0
        before = spent(db, done_at - timedelta(days=days), done_at, i.project_id) / max(before_days, 1.0)
        after = spent(db, now - timedelta(days=window), now, i.project_id) / window
        factor = min(after / before, MAX_ACTIVITY_FACTOR) if before else 0.0
        i.residual_usd_month = round(residual, 4)
        i.realized_usd_month = round(max(0.0, i.baseline_usd_month * factor - residual), 4)
        i.measured_at = now
        measured += 1
    return measured


def refresh(days: int = 90) -> int:
    """Recompute every insight. Returns the number of active findings."""
    global _last_refresh
    started = time.monotonic()
    now = datetime.now(UTC)
    with new_session() as db:
        ds = load(db, days)
        findings = {iid: f for iid, f in _run_miners(ds).items()
                    if f.type == "allowlist" or ds.monthly(f.est_usd) >= MIN_USD_MONTH}
        existing = {i.id: i for i in db.scalars(select(Insight))}
        for iid, f in findings.items():
            monthly = round(ds.monthly(f.est_usd), 4)
            row = existing.get(iid)
            if row is None:
                row = Insight(id=iid, first_seen=now, status="open")
                db.add(row)
            kind, path, content = f.artifact or (None, None, None)
            row.type, row.title, row.summary = f.type, f.title[:512], f.summary
            row.project_id, row.occurrences = f.project_id, f.occurrences
            row.est_tokens, row.est_usd, row.est_usd_month = f.est_tokens, round(f.est_usd, 4), monthly
            row.severity = _severity(f, monthly)
            row.evidence = json.dumps(f.evidence, default=str)
            row.artifact_kind, row.artifact_path, row.artifact_content = kind, path, content
            row.stale, row.updated_at = False, now
        for iid, row in existing.items():
            if iid not in findings:
                row.stale = True  # no longer observed in the window; hidden unless asked for
        measure_done(db, days, now)
        set_meta(db, "insights_refreshed_at", now.isoformat())
        db.commit()
    _last_refresh = time.monotonic()
    log.info("Insights refreshed: %d findings in %.2fs", len(findings), time.monotonic() - started)
    return len(findings)


def refresh_if_due(changed: bool) -> None:
    if _last_refresh == 0.0 or (changed and time.monotonic() - _last_refresh > REFRESH_SECONDS):
        refresh()
