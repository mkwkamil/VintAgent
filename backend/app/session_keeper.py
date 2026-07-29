"""Background watchdog that keeps the Vinted session warm.

Keeps the jar alive with cheap HTTP refresh (and optional residential proxy).
Chromium is optional and usually useless on datacenter IPs. When nothing works,
a phone rescue alert is sent.
"""

from __future__ import annotations

import logging
import threading
import time

from .browser_session import get_bootstrap
from .config import Settings, get_settings
from .session_rescue import notify_session_rescue_needed
from .session_store import get_session_store

logger = logging.getLogger(__name__)


class SessionKeeper:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_refresh_ok_at = 0.0

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
            if self._try_http_recover(require_new_token=True):
                return
            if self._settings.browser_bootstrap_enabled and get_bootstrap().ensure_session():
                return
            notify_session_rescue_needed(
                "Brak ważnej sesji Vinted (refresh token wygasł albo jar jest pusty)."
            )
            return

        force_due = (
            self._settings.session_force_refresh_seconds > 0
            and (time.time() - self._last_refresh_ok_at) >= self._settings.session_force_refresh_seconds
        )
        if not store.needs_refresh() and not force_due:
            return

        if self._try_http_recover(require_new_token=False):
            return

        logger.warning("Proactive session renewal failed")
        if self._settings.browser_bootstrap_enabled and get_bootstrap().ensure_session():
            self._last_refresh_ok_at = time.time()
            return
        notify_session_rescue_needed(
            "HTTP refresh sesji Vinted nie powiódł się — potrzebne świeże cookies albo VINTED_PROXY."
        )

    def _try_http_recover(self, *, require_new_token: bool) -> bool:
        from .scraper import VintedScraper

        scraper = VintedScraper(self._settings)
        try:
            if require_new_token:
                scraper.refresh_session()
                ok = not get_session_store().needs_bootstrap()
            else:
                ok = scraper.renew_session()
            if ok:
                self._last_refresh_ok_at = time.time()
                logger.info("Vinted session kept alive over HTTP")
            return ok
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
