"""Vinted session manager — Chrome CDP (CookieScraper style).

Jedna ścieżka: prawdziwy Google Chrome z remote debugging.
Scrapery czytają cookies z session_store i wołają curl_cffi.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from curl_cffi import requests as cffi

from .chrome_cdp import ACCESS_TOKEN_COOKIE, sync_cookies_from_cdp
from .config import Settings, get_settings
from .session_store import get_session_store

logger = logging.getLogger(__name__)

REFRESH_PATH = "/web/api/auth/refresh"
ACCEPT_LANGUAGES = ["pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7", "pl,en-US;q=0.9,en;q=0.8"]
CHROME_VERSION_RE = re.compile(r"Chrome/(\d+)")

_API_SEC = {
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def impersonate_for_ua(user_agent: str, profiles: list[str]) -> str:
    match = CHROME_VERSION_RE.search(user_agent)
    if match:
        major = match.group(1)
        for profile in profiles:
            if major in profile:
                return profile
    return profiles[0] if profiles else "chrome"


def api_headers(referer: str, accept_language: str, user_agent: str | None = None) -> dict[str, str]:
    store = get_session_store()
    parsed = urlparse(referer)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": accept_language,
        "Referer": referer,
        "Origin": origin,
        "X-Requested-With": "XMLHttpRequest",
        **_API_SEC,
    }
    if user_agent:
        headers["User-Agent"] = user_agent
    token = store.access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    _, cookies = store.snapshot()
    anon_id = cookies.get("anon_id")
    if anon_id:
        headers["X-Anon-Id"] = anon_id
    return headers


def open_http_session(settings: Settings, profile: str, user_agent: str | None = None) -> cffi.Session:
    kwargs: dict[str, Any] = {"impersonate": profile}
    proxy = (settings.vinted_proxy or "").strip()
    if proxy:
        kwargs["proxy"] = proxy
    session = cffi.Session(**kwargs)
    if user_agent:
        session.headers["User-Agent"] = user_agent
    return session


class SessionManager:
    """Utrzymuje jar cookies: dysk → HTTP refresh → Chrome CDP."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sync_lock = threading.Lock()
        self._recover_lock = threading.Lock()
        self._browser_ok = False
        self._last_error: str | None = None
        self._last_sync_at: datetime | None = None
        self._user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        )

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._settings.browser_bootstrap_enabled:
            logger.warning("Browser/CDP wyłączony — BROWSER_BOOTSTRAP_ENABLED=false")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._maintain_loop, name="vinted-cdp", daemon=True)
        self._thread.start()
        logger.info(
            "Vinted CDP manager start (cdp=%s, profile=%s)",
            self._settings.chrome_cdp_url,
            self._settings.browser_profile_dir,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def user_agent(self) -> str:
        return self._user_agent

    def impersonate_profile(self) -> str:
        return impersonate_for_ua(self._user_agent, self._settings.impersonate_profiles)

    def status(self) -> dict[str, Any]:
        store_status = get_session_store().status()
        return {
            **store_status,
            "browser_available": self._settings.browser_bootstrap_enabled,
            "browser_running": self._thread is not None and self._thread.is_alive(),
            "cdp_ok": self._cdp_ok(),
            "proxy_configured": bool((self._settings.vinted_proxy or "").strip()),
            "last_bootstrap_at": self._last_sync_at.isoformat(timespec="seconds") if self._last_sync_at else None,
            "last_bootstrap_error": self._last_error,
        }

    def _cdp_ok(self) -> bool:
        try:
            from .chrome_cdp import cdp_ws_ok

            return cdp_ws_ok(self._settings.chrome_cdp_url)
        except Exception:
            return False

    def ensure_ready(self, *, force: bool = False, timeout: float = 120.0) -> bool:
        store = get_session_store()
        if not force and store.has_access_token() and not store.needs_refresh() and not store.needs_bootstrap():
            return True

        # Zawsze najpierw tani HTTP refresh — CDP tylko gdy trzeba / HTTP pada.
        if store.has_access_token() and not store.needs_bootstrap():
            if self._http_refresh():
                return True
            if not force and not store.needs_refresh():
                return store.has_access_token()

        if not self._settings.browser_bootstrap_enabled:
            self._last_error = "Browser/CDP wyłączony w .env"
            return store.has_access_token() and not store.needs_bootstrap()

        return self._sync_from_chrome(force_login=force or store.needs_bootstrap(), timeout=timeout)

    def recover(self) -> bool:
        """Po 403: zawsze HTTP refresh, potem force CDP. Nie ufaj samemu JWT exp — Vinted może już odrzucić token."""
        with self._recover_lock:
            if self._http_refresh():
                logger.info("Recovery OK przez HTTP refresh")
                return True
            return self.ensure_ready(force=True, timeout=180.0)

    def push_manual_cookies(self, cookies: dict[str, str]) -> None:
        get_session_store().replace(cookies)
        self._last_sync_at = datetime.now(tz=timezone.utc)
        self._last_error = None
        self._browser_ok = True

    def _maintain_loop(self) -> None:
        from .chrome_cdp import cdp_ws_ok, ensure_cdp_chrome

        try:
            self.ensure_ready(force=False, timeout=180.0)
        except Exception:
            logger.exception("Pierwszy sync CDP nie powiódł się")

        while not self._stop.wait(self._settings.session_check_interval_seconds):
            try:
                settings = self._settings
                if settings.browser_bootstrap_enabled and not cdp_ws_ok(settings.chrome_cdp_url):
                    logger.warning("CDP health-check failed — restart Chromium")
                    ensure_cdp_chrome(
                        settings.chrome_cdp_url,
                        profile_dir=settings.browser_profile_dir,
                        chrome_path=settings.browser_executable_path or "/usr/bin/chromium",
                    )

                store = get_session_store()
                if store.needs_bootstrap() or store.needs_refresh():
                    self.ensure_ready(force=store.needs_bootstrap(), timeout=180.0)
            except Exception:
                logger.exception("CDP maintenance failed")

    def _sync_from_chrome(self, *, force_login: bool, timeout: float) -> bool:
        with self._sync_lock:
            settings = self._settings
            try:
                cookies, user_agent = sync_cookies_from_cdp(
                    cdp_url=settings.chrome_cdp_url,
                    base_url=settings.vinted_base_url,
                    profile_dir=settings.browser_profile_dir,
                    chrome_path=settings.browser_executable_path,
                    force_login=force_login,
                    login_timeout_seconds=min(timeout, 300.0),
                )
            except Exception as exc:
                self._last_error = str(exc)[:240]
                self._browser_ok = False
                logger.error("CDP sync failed: %s", exc)
                store = get_session_store()
                return store.has_access_token() and not store.needs_bootstrap()

            if ACCESS_TOKEN_COOKIE not in cookies:
                self._last_error = "Chrome nie zwrócił access_token_web"
                return False

            get_session_store().replace(cookies)
            if user_agent:
                self._user_agent = user_agent
            self._last_sync_at = datetime.now(tz=timezone.utc)
            self._last_error = None
            self._browser_ok = True
            remaining = get_session_store().seconds_until_expiry()
            logger.info(
                "Sesja z Chrome CDP (%d cookies%s)",
                len(cookies),
                f", access ~{remaining / 60:.0f} min" if remaining else "",
            )
            return True

    def _http_refresh(self) -> bool:
        store = get_session_store()
        if store.needs_bootstrap():
            return False

        settings = self._settings
        profile = self.impersonate_profile()
        base = settings.vinted_base_url.rstrip("/")

        with store.refresh_lock:
            session = open_http_session(settings, profile, self._user_agent)
            try:
                _, cookies = store.snapshot()
                domain = urlparse(base).hostname or ""
                for name, value in cookies.items():
                    session.cookies.set(name, value, domain=domain)
                response = session.post(
                    base + REFRESH_PATH,
                    headers=api_headers(base + "/", ACCEPT_LANGUAGES[0], self._user_agent),
                    timeout=settings.request_timeout_seconds,
                )
                if response.status_code != 200:
                    logger.warning("HTTP token refresh HTTP %s", response.status_code)
                    return False
                store.update(dict(session.cookies.items()))
                self._last_sync_at = datetime.now(tz=timezone.utc)
                self._last_error = None
                logger.info("HTTP refresh OK")
                return store.has_access_token()
            except Exception:
                logger.exception("HTTP refresh failed")
                return False
            finally:
                session.close()


_manager: SessionManager | None = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = SessionManager()
        return _manager
