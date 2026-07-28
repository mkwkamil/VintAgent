"""Lightweight Vinted catalog scraper.

No headless browser: ``curl_cffi`` reproduces a real Chrome TLS fingerprint, which
combined with rotated browser-like headers and a cookie bootstrap is what keeps
plain HTTP polling from being flagged instantly.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from curl_cffi import requests as cffi

from .config import Settings, get_settings
from .session_store import get_session_store

logger = logging.getLogger(__name__)

REFRESH_PATH = "/web/api/auth/refresh"

ACCEPT_LANGUAGES = ["pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7", "pl,en-US;q=0.9,en;q=0.8"]

# Browser catalog URLs use different parameter names than the JSON API.
LIST_PARAM_MAP = {
    "catalog[]": "catalog_ids",
    "catalog_ids[]": "catalog_ids",
    "brand[]": "brand_ids",
    "brand_ids[]": "brand_ids",
    "size[]": "size_ids",
    "size_ids[]": "size_ids",
    "status[]": "status_ids",
    "status_ids[]": "status_ids",
    "color[]": "color_ids",
    "color_ids[]": "color_ids",
    "material[]": "material_ids",
    "material_ids[]": "material_ids",
}

SCALAR_PARAMS = {
    "search_text",
    "price_from",
    "price_to",
    "currency",
    "order",
    "time",
    "is_for_swap",
}

CATALOG_PATH_RE = re.compile(r"/catalog/(\d+)")

# Cloudflare's managed JS challenge cannot be solved by any header or TLS tweak;
# it needs either a real browser or cookies borrowed from one.
CHALLENGE_MARKERS = ("challenge-platform", "cf-chl", "Just a moment")
COOKIE_HINT = "ustaw VINTED_COOKIE w .env (skopiuj Cookie z zalogowanej przeglądarki)"


class VintedBlocked(RuntimeError):
    """Raised on 401/403/429 so the caller can back off and rotate the session."""

    def __init__(self, status_code: int, hint: str | None = None) -> None:
        message = f"Vinted zablokował zapytanie (HTTP {status_code})"
        if hint:
            message = f"{message} — {hint}"
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class VintedItem:
    id: int
    title: str
    url: str
    price: str = ""
    brand: str = ""
    size: str = ""
    photo_url: str | None = None


def build_api_url(catalog_url: str, settings: Settings) -> str:
    """Translate a URL copied from the Vinted website into a catalog API call."""
    parsed = urlparse(catalog_url)
    origin_scheme = parsed.scheme or "https"
    origin_netloc = parsed.netloc or urlparse(settings.vinted_base_url).netloc

    if "/api/v2/catalog/items" in parsed.path:
        query = dict(parse_qsl(parsed.query, keep_blank_values=False))
        query.setdefault("per_page", str(settings.items_per_page))
        query.setdefault("page", "1")
        return urlunparse((origin_scheme, origin_netloc, parsed.path, "", urlencode(query, doseq=True), ""))

    lists: dict[str, list[str]] = {}
    scalars: dict[str, str] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key in LIST_PARAM_MAP:
            lists.setdefault(LIST_PARAM_MAP[key], []).extend(v for v in value.split(",") if v)
        elif key in SCALAR_PARAMS:
            scalars[key] = value

    path_catalog = CATALOG_PATH_RE.search(parsed.path)
    if path_catalog:
        catalog_ids = lists.setdefault("catalog_ids", [])
        if path_catalog.group(1) not in catalog_ids:
            catalog_ids.append(path_catalog.group(1))

    query = {
        "page": "1",
        "per_page": str(settings.items_per_page),
        "order": scalars.pop("order", "newest_first"),
        **scalars,
        **{key: ",".join(dict.fromkeys(values)) for key, values in lists.items() if values},
    }
    return urlunparse((origin_scheme, origin_netloc, "/api/v2/catalog/items", "", urlencode(query), ""))


def _is_challenge(response: Any) -> bool:
    try:
        body = response.text[:200_000]
    except Exception:
        return False
    return any(marker in body for marker in CHALLENGE_MARKERS)


def _price(raw: Any) -> str:
    if isinstance(raw, dict):
        amount = raw.get("amount")
        currency = raw.get("currency_code") or raw.get("currency") or ""
        if amount is None:
            return ""
        return f"{amount} {currency}".strip()
    return str(raw) if raw not in (None, "") else ""


def _photo_url(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    # Prefer a mid-size thumbnail: enough for Telegram, a fraction of the bandwidth.
    for thumb in raw.get("thumbnails") or []:
        if isinstance(thumb, dict) and thumb.get("type") in {"thumb310x430", "thumb428x624"}:
            return thumb.get("url")
    return raw.get("url")


class VintedScraper:
    """One instance per polling thread; owns its own cookie jar and identity."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._session: cffi.Session | None = None
        self._profile = random.choice(self.settings.impersonate_profiles)
        self._accept_language = random.choice(ACCEPT_LANGUAGES)
        self._store = get_session_store()
        self._cookie_version = -1

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                logger.debug("Ignoring error while closing session", exc_info=True)
            self._session = None

    def refresh_session(self) -> None:
        """Rotate identity and re-bootstrap cookies from the Vinted homepage."""
        self.close()
        self._profile = random.choice(self.settings.impersonate_profiles)
        self._accept_language = random.choice(ACCEPT_LANGUAGES)
        self._session = cffi.Session(impersonate=self._profile)
        self._cookie_version = -1
        self._sync_cookies()

        response = self._session.get(
            self.settings.vinted_base_url,
            headers=self._browser_headers(),
            timeout=self.settings.request_timeout_seconds,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            if _is_challenge(response):
                logger.warning(
                    "Cloudflare serves a JS challenge for %s; anonymous polling will fail, %s",
                    self.settings.vinted_base_url,
                    COOKIE_HINT,
                )
            else:
                logger.warning("Session bootstrap returned HTTP %s", response.status_code)

    def _sync_cookies(self) -> None:
        """Copy the shared cookie jar into this thread's session if it moved on."""
        if self._session is None:
            return
        version, cookies = self._store.snapshot()
        if version == self._cookie_version or not cookies:
            return
        domain = urlparse(self.settings.vinted_base_url).hostname or ""
        for name, value in cookies.items():
            self._session.cookies.set(name, value, domain=domain)
        self._cookie_version = version

    def _refresh_access_token(self) -> bool:
        """Renew the rotating token pair; only one thread may do this at a time."""
        if self._session is None or not self._store.configured:
            return False

        with self._store.refresh_lock:
            # Another thread may have refreshed while we waited for the lock.
            if self._cookie_version != self._store.snapshot()[0]:
                self._sync_cookies()
                if not self._store.needs_refresh():
                    return True

            self._sync_cookies()
            base = self.settings.vinted_base_url.rstrip("/")
            try:
                response = self._session.post(
                    f"{base}{REFRESH_PATH}",
                    headers=self._api_headers(f"{base}/"),
                    timeout=self.settings.request_timeout_seconds,
                )
            except Exception:
                logger.exception("Token refresh request failed")
                return False

            if response.status_code != 200:
                logger.warning("Token refresh returned HTTP %s", response.status_code)
                return False

            self._cookie_version = self._store.update(dict(self._session.cookies.items()))
            remaining = self._store.seconds_until_expiry()
            logger.info(
                "Refreshed Vinted session%s",
                f", valid for {remaining / 60:.0f} min" if remaining else "",
            )
            return True

    def _browser_headers(self) -> dict[str, str]:
        # Only language is set here; Accept, User-Agent and the Sec-* family come
        # from the impersonation profile and must stay consistent with its
        # TLS fingerprint.
        return {"Accept-Language": self._accept_language}

    def _api_headers(self, referer: str) -> dict[str, str]:
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": self._accept_language,
            "Referer": referer,
            "Origin": origin,
            "X-Requested-With": "XMLHttpRequest",
        }

    def fetch_items(self, catalog_url: str) -> list[VintedItem]:
        if self._session is None:
            self.refresh_session()

        self._sync_cookies()
        if self._store.needs_refresh():
            self._refresh_access_token()

        api_url = build_api_url(catalog_url, self.settings)
        response = self._request(api_url, catalog_url)

        # A stale token is the common case: renew it and retry before falling back
        # to rotating the whole identity.
        if response.status_code in (401, 403, 429):
            logger.warning("Catalog request blocked (%s), renewing session", response.status_code)
            if self._refresh_access_token():
                response = self._request(api_url, catalog_url)
            else:
                self.refresh_session()
                response = self._request(api_url, catalog_url)

        if response.status_code in (401, 403, 429):
            raise VintedBlocked(response.status_code, hint=self._blocked_hint(response))
        if response.status_code >= 400:
            raise RuntimeError(f"Vinted odpowiedział błędem HTTP {response.status_code}")

        payload = response.json()
        raw_items = payload.get("items") or payload.get("catalog_items") or []
        items = [parsed for raw in raw_items if (parsed := self._parse_item(raw)) is not None]
        return items

    def _request(self, api_url: str, referer: str) -> Any:
        assert self._session is not None
        return self._session.get(
            api_url,
            headers=self._api_headers(referer),
            timeout=self.settings.request_timeout_seconds,
        )

    def _blocked_hint(self, response: Any) -> str:
        if _is_challenge(response):
            return f"Cloudflare wymaga weryfikacji JS, {COOKIE_HINT}"
        if response.status_code == 429:
            return "limit zapytań, zwiększ POLL_MIN_SECONDS"
        if not self.settings.vinted_cookie:
            return f"brak ważnej sesji anonimowej, {COOKIE_HINT}"
        return "cookies z VINTED_COOKIE wygasły, skopiuj je ponownie z przeglądarki"

    def _parse_item(self, raw: Any) -> VintedItem | None:
        if not isinstance(raw, dict):
            return None
        try:
            item_id = int(raw["id"])
        except (KeyError, TypeError, ValueError):
            return None

        url = raw.get("url") or f"{self.settings.vinted_base_url.rstrip('/')}/items/{item_id}"
        return VintedItem(
            id=item_id,
            title=str(raw.get("title") or "Bez tytułu"),
            url=url,
            price=_price(raw.get("total_item_price") or raw.get("price")),
            brand=str(raw.get("brand_title") or ""),
            size=str(raw.get("size_title") or ""),
            photo_url=_photo_url(raw.get("photo")),
        )
