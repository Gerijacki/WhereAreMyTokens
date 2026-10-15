"""Optional dashboard authentication.

- WAMT_AUTH_PASSWORD set: the API requires a session cookie obtained by POST /api/auth/login.
  The cookie is `<expiry>.<hmac>` signed with WAMT_SECRET_KEY (or a key generated once and
  stored in the database), so no server-side session store is needed.
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
import secrets
import time
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from wamt.config import get_settings
from wamt.db import get_meta, new_session, set_meta

COOKIE = "wamt_session"
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


def _sign(expiry: int) -> str:
    mac = hmac.new(secret_key(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def valid_cookie(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    expiry, _, _mac = value.partition(".")
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    return hmac.compare_digest(_sign(int(expiry)), value)


def auth_required() -> bool:
    return bool(get_settings().auth_password)


def is_authenticated(request: Request) -> bool:
    s = get_settings()
    if not s.auth_password:
        return True
    if s.trust_proxy_auth_header and request.headers.get(s.trust_proxy_auth_header):
        return True
    return valid_cookie(request.cookies.get(COOKIE))


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
    return {"required": auth_required(), "authenticated": is_authenticated(request)}


@router.post("/login")
async def login(body: Login, request: Request, response: Response):
    expected = get_settings().auth_password
    if not expected:
        return {"authenticated": True}
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        await asyncio.sleep(1.0)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    expiry = int(time.time()) + get_settings().session_days * 86400
    response.set_cookie(COOKIE, _sign(expiry), max_age=get_settings().session_days * 86400, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https")
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"authenticated": False}
