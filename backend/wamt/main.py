import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from wamt import __version__
from wamt.api.analytics import router as analytics_router
from wamt.api.ingest_api import router as ingest_router
from wamt.api.metrics import router as metrics_router
from wamt.api.otel import router as otel_router
from wamt.api.routes import router
from wamt.auth import AuthMiddleware
from wamt.auth import router as auth_router
from wamt.collector.ingest import run_forever
from wamt.config import get_settings
from wamt.db import init_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_engine()
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
for r in (auth_router, router, analytics_router, ingest_router, otel_router, metrics_router):
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
