"""Vinted catalog scraper — reads cookies from session_manager, fetches via curl_cffi."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from curl_cffi import requests as cffi

from .config import Settings, get_settings
from .session_manager import ACCEPT_LANGUAGES, api_headers, get_session_manager, open_http_session
from .session_store import get_session_store

logger = logging.getLogger(__name__)

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


class VintedBlocked(RuntimeError):
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
    listed_ts: int | None = None


def build_api_url(catalog_url: str, settings: Settings) -> str:
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


def _price(raw: Any) -> str:
    if isinstance(raw, dict):
        amount = raw.get("amount")
        currency = raw.get("currency_code") or raw.get("currency") or ""
        if amount is None:
            return ""
        return f"{_amount(amount)} {currency}".strip()
    return str(raw) if raw not in (None, "") else ""


def _amount(raw: Any) -> str:
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
    for thumb in raw.get("thumbnails") or []:
        if isinstance(thumb, dict) and thumb.get("type") in {"thumb310x430", "thumb428x624"}:
            return thumb.get("url")
    return raw.get("url") or raw.get("full_size_url")


def _photo_urls(raw: dict[str, Any]) -> list[str]:
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
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._session: cffi.Session | None = None
        self._manager = get_session_manager()
        self._accept_language = random.choice(ACCEPT_LANGUAGES)
        self._store = get_session_store()
        self._cookie_version = -1
        self._open_http()

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                logger.debug("Ignoring error while closing session", exc_info=True)
            self._session = None

    def _open_http(self) -> None:
        profile = self._manager.impersonate_profile()
        self._session = open_http_session(self.settings, profile, self._manager.user_agent)
        self._cookie_version = -1

    def sync_cookies(self) -> None:
        if self._session is None:
            return
        version, cookies = self._store.snapshot()
        if version == self._cookie_version or not cookies:
            return
        domain = urlparse(self.settings.vinted_base_url).hostname or ""
        for name, value in cookies.items():
            self._session.cookies.set(name, value, domain=domain)
        self._cookie_version = version

    def _headers(self, referer: str) -> dict[str, str]:
        return api_headers(referer, self._accept_language, self._manager.user_agent)

    def _catalog_urls(self, catalog_url: str) -> list[str]:
        primary = build_api_url(catalog_url, self.settings)
        web = build_web_api_url(catalog_url, self.settings)
        return [primary] if primary == web else [primary, web]

    def _fetch_catalog(self, catalog_url: str) -> Any:
        assert self._session is not None
        response = None
        for api_url in self._catalog_urls(catalog_url):
            response = self._session.get(
                api_url,
                headers=self._headers(catalog_url),
                timeout=self.settings.request_timeout_seconds,
            )
            if response.status_code == 200:
                return response
        assert response is not None
        return response

    def fetch_items(self, catalog_url: str) -> list[VintedItem]:
        if not self._manager.ensure_ready():
            raise VintedBlocked(403, hint=self._manager.status().get("last_bootstrap_error"))

        self.sync_cookies()
        response = self._fetch_catalog(catalog_url)

        if response.status_code in (401, 403, 429):
            logger.warning("Catalog blocked (%s), asking browser to recover", response.status_code)
            if self._manager.recover():
                self.sync_cookies()
                response = self._fetch_catalog(catalog_url)

        if response.status_code in (401, 403, 429):
            raise VintedBlocked(response.status_code, hint=self._blocked_hint())

        if response.status_code >= 400:
            raise RuntimeError(f"Vinted odpowiedział błędem HTTP {response.status_code}")

        payload = response.json()
        raw_items = payload.get("items") or payload.get("catalog_items") or []
        return [parsed for raw in raw_items if (parsed := self._parse_item(raw)) is not None]

    def _blocked_hint(self) -> str:
        err = self._manager.status().get("last_bootstrap_error")
        if err:
            return str(err)
        return "Chromium nie odnowił sesji — sprawdź logi backendu"

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
        assert self._session is not None
        if not self._manager.ensure_ready():
            raise RuntimeError("Brak sesji Vinted")
        self.sync_cookies()

        base = self.settings.vinted_base_url.rstrip("/")
        response = self._session.get(
            f"{base}/api/v2/items/{item_id}",
            headers=self._headers(f"{base}/items/{item_id}"),
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code in (401, 403, 429) and self._manager.recover():
            self.sync_cookies()
            response = self._session.get(
                f"{base}/api/v2/items/{item_id}",
                headers=self._headers(f"{base}/items/{item_id}"),
                timeout=self.settings.request_timeout_seconds,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Item detail HTTP {response.status_code}")

        payload = response.json()
        item = payload.get("item") if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            item = payload if isinstance(payload, dict) else {}
        return _photo_urls(item)[:10]
