"""Lightweight Vinted catalog scraper.

Polling itself never opens a browser: ``curl_cffi`` reproduces a real Chrome TLS
fingerprint, which combined with browser-like headers and a valid cookie jar is
enough for plain HTTP requests. Only when the session cannot be recovered over
HTTP does :mod:`app.browser_session` step in with headless Chromium.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from curl_cffi import requests as cffi

from .browser_session import get_bootstrap
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
# it needs a real browser, which is what the Chromium bootstrap provides.
CHALLENGE_MARKERS = ("challenge-platform", "cf-chl", "Just a moment")


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
    total_price: str = ""
    brand: str = ""
    size: str = ""
    condition: str = ""
    photo_url: str | None = None
    photo_urls: list[str] = field(default_factory=list)
    # Unix timestamp of when the listing went up, used by the hour-of-day chart.
    listed_ts: int | None = None


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


def build_web_api_url(catalog_url: str, settings: Settings) -> str:
    """Web JSON endpoint — sometimes passes CF when /api/v2/catalog/items is blocked."""
    parsed = urlparse(catalog_url)
    origin_scheme = parsed.scheme or "https"
    origin_netloc = parsed.netloc or urlparse(settings.vinted_base_url).netloc

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
    return urlunparse(
        (origin_scheme, origin_netloc, "/web/api/core/catalog/items", "", urlencode(query), "")
    )

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
        return f"{_amount(amount)} {currency}".strip()
    return str(raw) if raw not in (None, "") else ""


def _amount(raw: Any) -> str:
    """Vinted sends "15.0"; show "15" and "18,65" the way a Polish price reads."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".replace(".", ",")


def _photo_url(raw: Any) -> str | None:
    if not isinstance(raw, dict):
        return None
    # Prefer a mid-size thumbnail: enough for Telegram, a fraction of the bandwidth.
    for thumb in raw.get("thumbnails") or []:
        if isinstance(thumb, dict) and thumb.get("type") in {"thumb310x430", "thumb428x624"}:
            return thumb.get("url")
    return raw.get("url") or raw.get("full_size_url")


def _photo_urls(raw: dict[str, Any]) -> list[str]:
    """Collect listing photos from the catalog payload when Vinted includes them."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)

    photos = raw.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            add(_photo_url(photo) if isinstance(photo, dict) else None)
    add(_photo_url(raw.get("photo")))
    return urls


def _listed_ts(raw: dict[str, Any]) -> int | None:
    """When the listing appeared; Vinted only exposes it via the photo upload."""
    candidates: list[Any] = [raw.get("created_at_ts")]
    photo = raw.get("photo")
    if isinstance(photo, dict):
        high_res = photo.get("high_resolution")
        if isinstance(high_res, dict):
            candidates.append(high_res.get("timestamp"))
        candidates.append(photo.get("high_resolution_timestamp"))

    for candidate in candidates:
        if isinstance(candidate, (int, float)) and candidate > 0:
            return int(candidate)
        if isinstance(candidate, str):
            try:
                return int(datetime.fromisoformat(candidate.replace("Z", "+00:00")).timestamp())
            except ValueError:
                continue
    return None


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

    def _open_session(self) -> cffi.Session:
        kwargs: dict[str, Any] = {"impersonate": self._profile}
        proxy = (self.settings.vinted_proxy or "").strip()
        if proxy:
            kwargs["proxy"] = proxy
        return cffi.Session(**kwargs)

    def refresh_session(self) -> None:
        """Rotate identity and make sure a usable cookie jar is in place."""
        self.close()
        self._profile = random.choice(self.settings.impersonate_profiles)
        self._accept_language = random.choice(ACCEPT_LANGUAGES)
        self._session = self._open_session()
        self._cookie_version = -1
        self._sync_cookies()

        need_token = self._store.needs_bootstrap()
        if self._http_bootstrap(require_access_token=need_token):
            return
        if self.settings.browser_bootstrap_enabled and get_bootstrap().ensure_session():
            self._sync_cookies()

    def _http_bootstrap(self, *, require_access_token: bool = False) -> bool:
        """Warm up / mint cookies with a cheap homepage request. False if blocked."""
        assert self._session is not None
        try:
            response = self._session.get(
                self.settings.vinted_base_url,
                headers=self._browser_headers(),
                timeout=self.settings.request_timeout_seconds,
                allow_redirects=True,
            )
        except Exception:
            logger.warning("Homepage bootstrap request failed", exc_info=True)
            return False

        if response.status_code < 400 and not _is_challenge(response):
            self._cookie_version = self._store.update(dict(self._session.cookies.items()))
            if require_access_token:
                ok = self._store.has_access_token()
                if not ok:
                    logger.info("Homepage returned cookies but no access_token_web")
                return ok
            return True
        if _is_challenge(response):
            logger.info("Cloudflare challenge on the homepage")
        else:
            logger.info("Homepage bootstrap returned HTTP %s", response.status_code)
        return False

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

    def renew_session(self) -> bool:
        """Get back to a working session, cheapest option first (no Chromium unless enabled)."""
        return self._recover_blocked(full_rotate=False)

    def _recover_blocked(self, *, full_rotate: bool = False) -> bool:
        """Try to fix 401/403: warm datadome cookies, refresh JWT, optional identity rotate."""
        if full_rotate:
            self.close()
            self._profile = random.choice(self.settings.impersonate_profiles)
            self._accept_language = random.choice(ACCEPT_LANGUAGES)
            self._session = self._open_session()
            self._cookie_version = -1

        if self._session is None:
            self._session = self._open_session()
            self._cookie_version = -1
        self._sync_cookies()

        # CF/DataDome cookies are IP-bound — homepage first, then token refresh.
        self._http_bootstrap(require_access_token=False)
        if self._refresh_access_token():
            return True
        if self._http_bootstrap(require_access_token=True):
            return True
        if self.settings.browser_bootstrap_enabled and get_bootstrap().ensure_session():
            self._sync_cookies()
            return True
        return False

    def _refresh_access_token(self) -> bool:
        """Renew the rotating token pair; only one thread may do this at a time."""
        if self._session is None or self._store.needs_bootstrap():
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
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": self._accept_language,
            "Referer": referer,
            "Origin": origin,
            "X-Requested-With": "XMLHttpRequest",
        }
        token = self._store.access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        _, cookies = self._store.snapshot()
        anon_id = cookies.get("anon_id")
        if anon_id:
            headers["X-Anon-Id"] = anon_id
        return headers

    def _catalog_urls(self, catalog_url: str) -> list[str]:
        settings = self.settings
        primary = build_api_url(catalog_url, settings)
        web = build_web_api_url(catalog_url, settings)
        return [primary] if primary == web else [primary, web]

    def _fetch_catalog(self, catalog_url: str) -> Any:
        """Try v2 then web catalog endpoints; return the last response."""
        assert self._session is not None
        response = None
        for api_url in self._catalog_urls(catalog_url):
            response = self._session.get(
                api_url,
                headers=self._api_headers(catalog_url),
                timeout=self.settings.request_timeout_seconds,
            )
            if response.status_code == 200:
                return response
        assert response is not None
        return response

    def fetch_items(self, catalog_url: str) -> list[VintedItem]:
        if self._session is None:
            self.refresh_session()

        self._sync_cookies()
        if self._store.needs_bootstrap():
            self.refresh_session()
        elif self._store.needs_refresh():
            self._refresh_access_token()

        response = self._fetch_catalog(catalog_url)

        if response.status_code in (401, 403, 429):
            logger.warning("Catalog request blocked (%s), recovering session", response.status_code)
            if self._recover_blocked():
                response = self._fetch_catalog(catalog_url)

        if response.status_code in (401, 403, 429):
            logger.warning("Still blocked (%s), rotating TLS identity", response.status_code)
            if self._recover_blocked(full_rotate=True):
                response = self._fetch_catalog(catalog_url)

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
        if response.status_code == 429:
            return "limit zapytań, zwiększ POLL_MIN_SECONDS"
        if (self.settings.vinted_proxy or "").strip():
            return (
                "Cloudflare blokuje mimo proxy — wklej świeże cookies "
                "(Wklej / alert Telegram) albo zmień VINTED_PROXY"
            )
        bootstrap = get_bootstrap()
        if bootstrap.status()["browser_available"]:
            error = bootstrap.status()["last_bootstrap_error"]
            if error:
                return f"odnawianie sesji przeglądarką nie powiodło się: {error}"
            if _is_challenge(response):
                return "Cloudflare wymaga weryfikacji JS — włącz BROWSER_BOOTSTRAP_ENABLED"
            return "sesja Vinted wygasła — włącz bootstrap albo wklej cookies"
        return (
            "Cloudflare blokuje IP serwera (403) — ustaw VINTED_PROXY (residential) "
            "albo wklej świeże cookies; skopiowany session.json z domu zwykle nie działa na GCP"
        )

    def _parse_item(self, raw: Any) -> VintedItem | None:
        if not isinstance(raw, dict):
            return None
        try:
            item_id = int(raw["id"])
        except (KeyError, TypeError, ValueError):
            return None

        url = raw.get("url") or f"{self.settings.vinted_base_url.rstrip('/')}/items/{item_id}"
        price = _price(raw.get("price"))
        total_price = _price(raw.get("total_item_price"))
        photos = _photo_urls(raw)
        return VintedItem(
            id=item_id,
            title=str(raw.get("title") or "Bez tytułu"),
            url=url,
            price=price or total_price,
            total_price=total_price if total_price != price else "",
            brand=str(raw.get("brand_title") or ""),
            size=str(raw.get("size_title") or ""),
            condition=str(raw.get("status") or ""),
            photo_url=photos[0] if photos else None,
            photo_urls=photos,
            listed_ts=_listed_ts(raw),
        )

    def fetch_item_photos(self, item_id: int) -> list[str]:
        """Load up to 10 photo URLs for a listing (used by the More photos button)."""
        if self._session is None:
            self.refresh_session()
        assert self._session is not None
        self._sync_cookies()

        base = self.settings.vinted_base_url.rstrip("/")
        response = self._session.get(
            f"{base}/api/v2/items/{item_id}",
            headers=self._api_headers(f"{base}/items/{item_id}"),
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code in (401, 403, 429):
            if self.renew_session():
                response = self._session.get(
                    f"{base}/api/v2/items/{item_id}",
                    headers=self._api_headers(f"{base}/items/{item_id}"),
                    timeout=self.settings.request_timeout_seconds,
                )
        if response.status_code >= 400:
            raise RuntimeError(f"Item detail HTTP {response.status_code}")

        payload = response.json()
        item = payload.get("item") if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            item = payload if isinstance(payload, dict) else {}
        return _photo_urls(item)[:10]
