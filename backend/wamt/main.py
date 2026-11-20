import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from wamt import __version__
from wamt.api.analytics import router as analytics_router
from wamt.api.export import router as export_router
from wamt.api.ingest_api import router as ingest_router
from wamt.api.metrics import router as metrics_router
from wamt.api.otel import router as otel_router
from wamt.api.routes import router
from wamt.api.settings import router as settings_router
from wamt.api.spend import router as spend_router
from wamt.auth import AuthMiddleware, auth_required
from wamt.auth import router as auth_router
from wamt.collector.ingest import run_forever
from wamt.config import get_settings
from wamt.db import init_engine
from wamt.security import BodyLimitMiddleware, SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine()
    if not auth_required() and not settings.trust_proxy_auth_header:
        logging.getLogger("wamt").warning(
            "No dashboard authentication is configured: anyone who can reach this port can read your usage "
            "data, create device tokens and set the password. Set WAMT_AUTH_PASSWORD, or keep the port on "
            "localhost / behind an authenticating proxy.")
    elif settings.trust_proxy_auth_header and not settings.trusted_proxy_ips:
        logging.getLogger("wamt").warning(
            "WAMT_TRUST_PROXY_AUTH_HEADER is set without WAMT_TRUSTED_PROXY_IPS: any client that can reach "
            "this port directly can send that header. Restrict the port to the proxy or set the IPs.")
    stop = threading.Event()
    worker = None
    if settings.ingest_enabled:
        worker = threading.Thread(target=run_forever, args=(stop,), name="wamt-ingest", daemon=True)
        worker.start()
    yield
    stop.set()
    if worker:
        worker.join(timeout=10)


app = FastAPI(title="WhereAreMyTokens", version=__version__, lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)  # outermost, so it also covers 401/413 answers
for r in (auth_router, router, analytics_router, spend_router, settings_router, export_router, ingest_router, otel_router, metrics_router):
    app.include_router(r)


def _mount_spa(static_dir: Path) -> None:
    """Serve the built dashboard; unknown non-API paths fall back to index.html (client routing)."""
    index = static_dir / "index.html"
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


_static = get_settings().static_dir
if _static and (_static / "index.html").exists():
    _mount_spa(_static)
