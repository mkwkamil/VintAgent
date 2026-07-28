"""Background watchdog that keeps the Vinted session warm.

Without it the session would only ever be renewed by a poll that already failed,
so the first request after a quiet period would burn a retry (and often a
Telegram-visible error). The keeper checks every few minutes and renews ahead of
expiry: an HTTP token refresh normally, Chromium only when there is nothing left
to refresh from.
"""

from __future__ import annotations

import logging
import threading

from .browser_session import get_bootstrap
from .config import Settings, get_settings
from .session_store import get_session_store

logger = logging.getLogger(__name__)


class SessionKeeper:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="session-keeper", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        # Give the API a moment to come up before the first (possibly slow) check.
        delay = 5.0
        while not self._stop.wait(delay):
            delay = self._settings.session_check_interval_seconds
            try:
                self._tick()
            except Exception:
                logger.exception("Session keeper iteration failed")

    def _tick(self) -> None:
        store = get_session_store()
        if store.needs_bootstrap():
            logger.info("No usable Vinted session, bootstrapping with Chromium")
            get_bootstrap().ensure_session()
            return
        if store.needs_refresh():
            # Import here: the scraper pulls in curl_cffi, which we only want
            # loaded in processes that actually talk to Vinted.
            from .scraper import VintedScraper

            scraper = VintedScraper(self._settings)
            try:
                if not scraper.renew_session():
                    logger.warning("Proactive session renewal failed, will retry")
            finally:
                scraper.close()


_keeper: SessionKeeper | None = None
_keeper_lock = threading.Lock()


def get_keeper() -> SessionKeeper:
    global _keeper
    with _keeper_lock:
        if _keeper is None:
            _keeper = SessionKeeper()
        return _keeper
