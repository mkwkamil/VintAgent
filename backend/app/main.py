"""VintAgent FastAPI application.

Single-container design: this app serves the JSON API under ``/api`` and the
compiled React bundle (copied into ``static_dir`` by the Docker build) at ``/``.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__, storage
from .api import api_router
from .config import get_settings
from .session_manager import get_session_manager
from .storage import STATUS_RUNNING, STATUS_STOPPED
from .thread_manager import MaxThreadsReached, get_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
# Dashboard polls /api every 10s — hide those 200 lines so Vinted errors stand out.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _resume_running_urls() -> None:
    """Bring back the threads that were active before the last shutdown."""
    manager = get_manager()
    for record in storage.list_urls():
        if record.get("status") != STATUS_RUNNING:
            continue
        try:
            manager.start(record["id"])
        except MaxThreadsReached as exc:
            logger.warning("Cannot resume '%s': %s", record.get("name"), exc)
            storage.set_status(record["id"], STATUS_STOPPED)


def _bootstrap_session_then_resume() -> None:
    manager = get_session_manager()
    if manager.ensure_ready(force=True, timeout=180.0):
        logger.info("Vinted session ready")
    else:
        logger.warning(
            "Vinted session not ready: %s",
            manager.status().get("last_bootstrap_error") or "unknown",
        )
    _resume_running_urls()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.data_file.resolve() == settings.session_file.resolve():
        logger.error(
            "DATA_FILE and SESSION_FILE wskazują ten sam plik (%s) — popraw .env",
            settings.data_file,
        )
    logger.info("VintAgent %s starting (data file: %s)", __version__, settings.data_file)
    if not settings.telegram_enabled:
        logger.warning("Telegram is not configured; notifications will be skipped")
    get_session_manager().start()
    # Scrapery dopiero po bootstrapie — inaczej wszystkie dostają 403 zanim CDP skończy sync.
    threading.Thread(
        target=_bootstrap_session_then_resume,
        name="session-bootstrap",
        daemon=True,
    ).start()
    try:
        yield
    finally:
        get_session_manager().stop()
        get_manager().stop_all()
        logger.info("VintAgent stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="VintAgent", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    # Mounted last so it acts as the SPA catch-all without shadowing /api routes.
    # Absent during local backend-only development, when Vite serves the frontend.
    if settings.static_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")

    return app


app = create_app()
