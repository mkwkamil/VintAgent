"""Cookie bootstrap through a real headless browser.

Cloudflare's managed challenge is JavaScript: no header or TLS trick solves it,
only an engine that runs the script. Chromium is therefore kept as a *last
resort* — day to day the session is renewed with a plain HTTP token refresh
(a few kB), and the browser is launched only when there is no usable session at
all.

On residential IPs this usually works. On datacenter IPs (GCP, AWS, …) Cloudflare
often never issues ``access_token_web``; in that case seed the jar by copying
``session.json`` from a machine that can bootstrap, then let HTTP refresh keep
it alive.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings
from .session_store import ACCESS_TOKEN_COOKIE, get_session_store

logger = logging.getLogger(__name__)

# Images/media/fonts are pure overhead. Stylesheets stay: Cloudflare's challenge
# page sometimes needs CSS before the JS finishes and issues cookies.
BLOCKED_RESOURCES = {"image", "media", "font"}

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--mute-audio",
    "--disable-blink-features=AutomationControlled",
]


class BrowserUnavailable(RuntimeError):
    """Playwright or its Chromium build is missing from this environment."""


class BrowserBootstrap:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._available: bool | None = None

    # -------------------------------------------------------------- inspection

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                import playwright.sync_api  # noqa: F401

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def status(self) -> dict[str, Any]:
        return {
            "browser_available": self.available and self._settings.browser_bootstrap_enabled,
            "last_bootstrap_at": self._last_success_at.isoformat(timespec="seconds")
            if self._last_success_at
            else None,
            "last_bootstrap_error": self._last_error,
        }

    # ------------------------------------------------------------------ running

    def ensure_session(self, *, force: bool = False) -> bool:
        """Fetch a fresh cookie jar with Chromium. Returns True on success.

        Only one caller runs the browser at a time; the others either wait and
        reuse the cookies it produced, or are turned away by the rate limit.
        """
        settings = self._settings
        if not settings.browser_bootstrap_enabled:
            return False
        if not self.available:
            self._last_error = "Playwright nie jest zainstalowany"
            return False

        store = get_session_store()
        version_before = store.snapshot()[0]

        with self._lock:
            # A queued caller only needs the result, and someone just produced it.
            if not force and store.snapshot()[0] != version_before and store.has_access_token():
                return True

            waited = time.monotonic() - self._last_attempt
            if not force and self._last_attempt and waited < settings.browser_min_interval_seconds:
                logger.debug("Skipping browser bootstrap, retried too soon (%.0fs)", waited)
                return False
            self._last_attempt = time.monotonic()

            try:
                cookies = self._collect_cookies()
            except BrowserUnavailable as exc:
                self._available = False
                self._last_error = str(exc)
                logger.error("Browser bootstrap unavailable: %s", exc)
                return False
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.exception("Browser bootstrap failed")
                return False

            if ACCESS_TOKEN_COOKIE not in cookies:
                self._last_error = (
                    "Vinted nie wydał tokenu sesji (Cloudflare na IP serwera). "
                    "Skopiuj backend/data/session.json z lokalnej maszyny albo wklej cookies w panelu."
                )
                logger.warning(
                    "Browser bootstrap finished without %s (got: %s)",
                    ACCESS_TOKEN_COOKIE,
                    sorted(cookies) or "no cookies",
                )
                return False

            store.update(cookies)
            self._last_success_at = datetime.now(tz=timezone.utc)
            self._last_error = None
            remaining = store.seconds_until_expiry()
            logger.info(
                "Bootstrapped Vinted session with Chromium (%d cookies%s)",
                len(cookies),
                f", token valid for {remaining / 60:.0f} min" if remaining else "",
            )
            return True

    def _collect_cookies(self) -> dict[str, str]:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        settings = self._settings
        timeout_ms = int(settings.browser_timeout_seconds * 1000)

        with sync_playwright() as playwright:
            launch_kwargs: dict[str, Any] = {"headless": True, "args": CHROMIUM_ARGS}
            if settings.browser_executable_path:
                launch_kwargs["executable_path"] = settings.browser_executable_path
            try:
                browser = playwright.chromium.launch(**launch_kwargs)
            except PlaywrightError as exc:
                raise BrowserUnavailable(str(exc).splitlines()[0]) from exc

            try:
                context = browser.new_context(
                    locale=settings.browser_locale,
                    timezone_id=settings.browser_timezone,
                    viewport={"width": 1365, "height": 900},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )
                page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in BLOCKED_RESOURCES
                    else route.continue_(),
                )
                page.goto(settings.vinted_base_url, wait_until="domcontentloaded", timeout=timeout_ms)
                self._wait_for_token(page, context, timeout_ms)
                cookies = {
                    cookie["name"]: cookie["value"]
                    for cookie in context.cookies()
                    if cookie.get("name") and cookie.get("value")
                }
                if ACCESS_TOKEN_COOKIE not in cookies:
                    self._log_failure_context(page, cookies)
                return cookies
            finally:
                browser.close()

    def _log_failure_context(self, page: Any, cookies: dict[str, str]) -> None:
        title = ""
        url = ""
        snippet = ""
        try:
            title = page.title()
            url = page.url
            snippet = (page.content() or "")[:400].replace("\n", " ")
        except Exception:
            logger.debug("Could not read page context after failed bootstrap", exc_info=True)
        logger.warning(
            "Bootstrap page title=%r url=%r cookies=%s body≈%r",
            title,
            url,
            sorted(cookies),
            snippet,
        )

    @staticmethod
    def _wait_for_token(page: Any, context: Any, timeout_ms: int) -> None:
        """Poll the jar until Vinted issues an anonymous token or time runs out.

        A Cloudflare challenge resolves itself after a few seconds and only then
        does the real page (and its Set-Cookie) arrive, so waiting on the cookie
        is more reliable than waiting on any load event.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if any(cookie.get("name") == ACCESS_TOKEN_COOKIE for cookie in context.cookies()):
                return
            page.wait_for_timeout(500)


_bootstrap: BrowserBootstrap | None = None
_bootstrap_lock = threading.Lock()


def get_bootstrap() -> BrowserBootstrap:
    global _bootstrap
    with _bootstrap_lock:
        if _bootstrap is None:
            _bootstrap = BrowserBootstrap()
        return _bootstrap
