"""VintAgent FastAPI application.

Single-container design: this app serves the JSON API under ``/api`` and the
compiled React bundle (copied into ``static_dir`` by the Docker build) at ``/``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__, storage
from .api import api_router
from .config import get_settings
from .session_keeper import get_keeper
from .storage import STATUS_RUNNING, STATUS_STOPPED
from .thread_manager import MaxThreadsReached, get_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("VintAgent %s starting (data file: %s)", __version__, settings.data_file)
    if not settings.telegram_enabled:
        logger.warning("Telegram is not configured; notifications will be skipped")
    get_keeper().start()
    _resume_running_urls()
    try:
        yield
    finally:
        get_keeper().stop()
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
