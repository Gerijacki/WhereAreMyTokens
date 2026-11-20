"""Optional dashboard authentication.

- A password, from WAMT_AUTH_PASSWORD or set in Settings (stored as a salted scrypt hash in the
  `meta` table; the environment variable wins): the API requires a session cookie obtained by
  POST /api/auth/login.
  The cookie is `<expiry>.<hmac>` signed with WAMT_SECRET_KEY (or a key generated once and
  stored in the database), so no server-side session store is needed. The signature also covers
  the current password, so changing or removing it signs every other browser out.
- WAMT_TRUST_PROXY_AUTH_HEADER set: a request carrying that header (added by an authenticating
  reverse proxy such as Authelia or oauth2-proxy) is trusted.
- Neither set: open, which is fine on localhost or behind a proxy that already authenticates.

Machine endpoints use their own credentials: /api/ingest and /v1/* take device tokens,
/metrics takes WAMT_METRICS_TOKEN.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import secrets
import time
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from wamt.config import get_settings
from wamt.db import Meta, get_meta, new_session, set_meta

log = logging.getLogger(__name__)
COOKIE = "wamt_session"
PASSWORD_META = "auth_password_hash"
MIN_PASSWORD = 8
# Paths that never need the dashboard cookie (they're public or use their own token).
OPEN_PATHS = ("/api/health", "/api/auth/", "/api/ingest", "/v1/", "/metrics")

router = APIRouter(prefix="/api/auth")


@lru_cache
def secret_key() -> bytes:
    configured = get_settings().secret_key
    if configured:
        return configured.encode()
    with new_session() as db:
        key = get_meta(db, "secret_key")
        if key is None:
            key = secrets.token_hex(32)
            set_meta(db, "secret_key", key)
            db.commit()
    return key.encode()


@lru_cache
def stored_hash() -> str | None:
    """Password hash saved from Settings. Cached; cleared whenever it changes."""
    with new_session() as db:
        return get_meta(db, PASSWORD_META)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _matches_hash(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest)


def password_source() -> str:
    """Where the dashboard password comes from: env, ui or none."""
    if get_settings().auth_password:
        return "env"
    return "ui" if stored_hash() else "none"


def check_password(password: str) -> bool:
    env = get_settings().auth_password
    if env:
        return hmac.compare_digest(password.encode(), env.encode())
    stored = stored_hash()
    return bool(stored) and _matches_hash(password, stored)


def _password_fingerprint() -> str:
    current = get_settings().auth_password or stored_hash() or ""
    return hashlib.sha256(current.encode()).hexdigest()[:16]


def _sign(expiry: int) -> str:
    payload = f"{expiry}|{_password_fingerprint()}".encode()
    mac = hmac.new(secret_key(), payload, hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def valid_cookie(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    expiry, _, _mac = value.partition(".")
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    return hmac.compare_digest(_sign(int(expiry)), value)


def auth_required() -> bool:
    return password_source() != "none"


def _from_trusted_proxy(request: Request) -> bool:
    """With WAMT_TRUSTED_PROXY_IPS set, only those peers may vouch for a user via the proxy header."""
    allowed = get_settings().trusted_proxy_ips
    if not allowed:
        return True
    try:
        peer = ipaddress.ip_address(request.client.host) if request.client else None
    except ValueError:
        return False
    nets = []
    for item in allowed.split(","):
        if item.strip():
            try:
                nets.append(ipaddress.ip_network(item.strip(), strict=False))
            except ValueError:
                log.warning("Ignoring invalid WAMT_TRUSTED_PROXY_IPS entry %r", item)
    return peer is not None and any(peer in n for n in nets)


def is_authenticated(request: Request) -> bool:
    s = get_settings()
    if not auth_required():
        return True
    if (s.trust_proxy_auth_header and request.headers.get(s.trust_proxy_auth_header)
            and _from_trusted_proxy(request)):
        return True
    return valid_cookie(request.cookies.get(COOKIE))


# Failed logins per client IP: ip -> (count, window start). In memory, so a restart clears it.
_failures: dict[str, tuple[int, float]] = {}
LOCKOUT_SECONDS = 15 * 60


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _locked_out(ip: str) -> int:
    """Seconds left on the lockout for this client, or 0."""
    count, since = _failures.get(ip, (0, 0.0))
    left = since + LOCKOUT_SECONDS - time.monotonic()
    if count >= get_settings().login_max_attempts and left > 0:
        return int(left) + 1
    if left <= 0:
        _failures.pop(ip, None)
    return 0


def _record_failure(ip: str) -> None:
    count, since = _failures.get(ip, (0, time.monotonic()))
    _failures[ip] = (count + 1, since)
    if len(_failures) > 10_000:  # bounded memory under a spray of spoofed sources
        _failures.pop(next(iter(_failures)))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.startswith(OPEN_PATHS) and not is_authenticated(request):
            return JSONResponse({"detail": "Login required"}, status_code=401)
        return await call_next(request)


class Login(BaseModel):
    password: str


@router.get("/status")
def status(request: Request):
    s = get_settings()
    return {"required": auth_required(), "authenticated": is_authenticated(request),
            "source": password_source(), "proxy_header": s.trust_proxy_auth_header}


def _start_session(request: Request, response: Response) -> None:
    s = get_settings()
    secure = s.cookie_secure if s.cookie_secure is not None else request.url.scheme == "https"
    response.set_cookie(COOKIE, _sign(int(time.time()) + s.session_days * 86400), max_age=s.session_days * 86400,
                        httponly=True, samesite="lax", secure=secure)


@router.post("/login")
async def login(body: Login, request: Request, response: Response):
    if not auth_required():
        return {"authenticated": True}
    ip = _client_ip(request)
    if wait := _locked_out(ip):
        raise HTTPException(429, "Too many wrong passwords. Try again later.", headers={"Retry-After": str(wait)})
    if not check_password(body.password):
        _record_failure(ip)
        await asyncio.sleep(1.0)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    _failures.pop(ip, None)
    _start_session(request, response)
    return {"authenticated": True}


class PasswordChange(BaseModel):
    current: str | None = None
    new: str


class PasswordRemoval(BaseModel):
    current: str


async def _require_current(request: Request, current: str | None) -> None:
    if password_source() == "env":
        raise HTTPException(409, "The password is set with WAMT_AUTH_PASSWORD; change it there")
    if password_source() == "ui":
        ip = _client_ip(request)
        if wait := _locked_out(ip):
            raise HTTPException(429, "Too many wrong passwords. Try again later.",
                                headers={"Retry-After": str(wait)})
        if not (is_authenticated(request) and current and check_password(current)):
            _record_failure(ip)
            await asyncio.sleep(1.0)
            raise HTTPException(403, "Current password is wrong")


def _save_hash(value: str | None) -> None:
    with new_session() as db:
        if value is None:
            row = db.get(Meta, PASSWORD_META)
            if row is not None:
                db.delete(row)
        else:
            set_meta(db, PASSWORD_META, value)
        db.commit()
    stored_hash.cache_clear()


@router.put("/password")
async def set_password(body: PasswordChange, request: Request, response: Response):
    """Set the dashboard password (anyone can while there is none), or change it with the current one."""
    await _require_current(request, body.current)
    if len(body.new) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters")
    _save_hash(hash_password(body.new))
    _start_session(request, response)  # keep this browser signed in; every other session ends
    return {"source": password_source()}


@router.delete("/password")
async def remove_password(body: PasswordRemoval, request: Request, response: Response):
    await _require_current(request, body.current)
    if password_source() == "none":
        raise HTTPException(404, "No password is set")
    _save_hash(None)
    response.delete_cookie(COOKIE)
    return {"source": password_source()}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"authenticated": False}
