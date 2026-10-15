"""Run the miners and persist their findings, keeping each insight's status across refreshes."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select

from wamt.db import Insight, new_session, set_meta
from wamt.insights.data import load
from wamt.insights.miners import MINERS, Finding

log = logging.getLogger(__name__)
REFRESH_SECONDS = 600
MIN_USD_MONTH = 0.10  # below this a finding is noise
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


def refresh(days: int = 90) -> int:
    """Recompute every insight. Returns the number of active findings."""
    global _last_refresh
    started = time.monotonic()
    now = datetime.now(UTC)
    with new_session() as db:
        ds = load(db, days)
        findings: dict[str, Finding] = {}
        for miner in MINERS:
            try:
                for f in miner(ds):
                    if f.type != "allowlist" and ds.monthly(f.est_usd) < MIN_USD_MONTH:
                        continue
                    findings[insight_id(f)] = f
            except Exception:
                log.exception("Insight miner %s failed", miner.__name__)
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
        set_meta(db, "insights_refreshed_at", now.isoformat())
        db.commit()
    _last_refresh = time.monotonic()
    log.info("Insights refreshed: %d findings in %.2fs", len(findings), time.monotonic() - started)
    return len(findings)


def refresh_if_due(changed: bool) -> None:
    if _last_refresh == 0.0 or (changed and time.monotonic() - _last_refresh > REFRESH_SECONDS):
        refresh()
