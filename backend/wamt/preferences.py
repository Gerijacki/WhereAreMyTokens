"""Display preferences: currency, exchange rate, plan and billing.

Each value comes from, in order: a WAMT_* environment variable that is explicitly set (the field is
then locked in Settings), the value saved from Settings (a JSON object in the `meta` table), or the
default in config.py.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from wamt.config import get_settings
from wamt.db import get_meta, set_meta
from wamt.pricing import load_plans

FIELDS = ("currency", "eur_per_usd", "plan", "billing")
CURRENCIES = ("EUR", "USD")
BILLING = ("monthly", "annual")
META_KEY = "settings"


class PreferenceError(ValueError):
    pass


class LockedError(PreferenceError):
    pass


def locked() -> set[str]:
    """Fields set through the environment, which Settings can't change."""
    return set(get_settings().model_fields_set) & set(FIELDS)


def _saved(db: Session) -> dict:
    raw = get_meta(db, META_KEY)
    return json.loads(raw) if raw else {}


def effective(db: Session) -> dict:
    s = get_settings()
    saved, env = _saved(db), locked()
    out = {f: getattr(s, f) if f in env or f not in saved else saved[f] for f in FIELDS}
    if out["plan"] not in {p.id for p in load_plans()}:
        out["plan"] = None
    return out


def _validate(field: str, value):
    if field == "currency":
        value = str(value).upper()
        if value not in CURRENCIES:
            raise PreferenceError(f"currency must be one of {', '.join(CURRENCIES)}")
    elif field == "eur_per_usd":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise PreferenceError("eur_per_usd must be a number") from None
        if not 0 < value < 100:
            raise PreferenceError("eur_per_usd must be between 0 and 100")
    elif field == "billing":
        if value not in BILLING:
            raise PreferenceError(f"billing must be one of {', '.join(BILLING)}")
    elif field == "plan":
        if value is not None and value not in {p.id for p in load_plans()}:
            raise PreferenceError(f"unknown plan {value!r}")
    else:
        raise PreferenceError(f"unknown setting {field!r}")
    return value


def update(db: Session, changes: dict) -> dict:
    """Validate and save the given fields. Raises LockedError for fields set through the environment."""
    env = locked()
    blocked = sorted(set(changes) & env)
    if blocked:
        raise LockedError(", ".join(f"WAMT_{f.upper()}" for f in blocked) + " is set in the environment")
    saved = _saved(db)
    for field, value in changes.items():
        saved[field] = _validate(field, value)
    set_meta(db, META_KEY, json.dumps(saved))
    db.commit()
    return effective(db)


def money(db: Session, usd: float) -> str:
    """Format a USD amount in the display currency, for alerts."""
    p = effective(db)
    if p["currency"] == "EUR":
        return f"€{usd * p['eur_per_usd']:,.2f}"
    return f"${usd:,.2f}"
