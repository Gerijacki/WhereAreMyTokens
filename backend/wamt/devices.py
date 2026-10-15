"""Device tokens for `wamt agent`. Tokens are shown once; only their SHA-256 is stored."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from wamt.db import Device

TOKEN_PREFIX = "wamt_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: Session, name: str) -> str:
    if db.scalar(select(Device).where(Device.name == name)):
        raise ValueError(f"A device named {name!r} already exists")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    db.add(Device(name=name, token_hash=_hash(token), created_at=datetime.now(UTC), revoked=False))
    db.commit()
    return token


def verify(db: Session, token: str | None) -> Device | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    device = db.scalar(select(Device).where(Device.token_hash == _hash(token)))
    if device is None or device.revoked:
        return None
    return device


def revoke(db: Session, name: str) -> bool:
    device = db.scalar(select(Device).where(Device.name == name))
    if device is None:
        return False
    device.revoked = True
    db.commit()
    return True


def bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None
