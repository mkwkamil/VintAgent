"""Shared Vinted cookie jar with persistence.

Vinted rotates *both* tokens on every refresh: the old refresh token dies the
moment a new one is issued. That makes the cookie set a single piece of shared
mutable state — every scraper thread must read from and write to this store, and
only one refresh may be in flight at a time (``refresh_lock``), otherwise threads
would invalidate each other's tokens.

Cookies are imported manually (awaryjny Wklej) or synced automatically from the
persistent Chromium profile in :mod:`app.session_manager`.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

ACCESS_TOKEN_COOKIE = "access_token_web"
REFRESH_TOKEN_COOKIE = "refresh_token_web"


def parse_cookie_header(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for chunk in raw.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies


def _strip_cookie_value(raw: str, name: str) -> str:
    """Accept a bare value or ``name=value`` pasted from mobile inspectors."""
    text = raw.strip()
    if not text:
        return ""
    if "=" in text and text.split("=", 1)[0].strip() == name:
        return text.split("=", 1)[1].strip()
    return text


def cookies_from_fields(
    *,
    access_token: str,
    refresh_token: str,
    datadome: str | None = None,
    cf_clearance: str | None = None,
    anon_id: str | None = None,
    cf_bm: str | None = None,
) -> dict[str, str]:
    cookies = {
        ACCESS_TOKEN_COOKIE: _strip_cookie_value(access_token, ACCESS_TOKEN_COOKIE),
        REFRESH_TOKEN_COOKIE: _strip_cookie_value(refresh_token, REFRESH_TOKEN_COOKIE),
    }
    optional = {
        "datadome": datadome,
        "cf_clearance": cf_clearance,
        "anon_id": anon_id,
        "__cf_bm": cf_bm,
    }
    for name, value in optional.items():
        if value and (clean := _strip_cookie_value(value, name)):
            cookies[name] = clean
    return cookies


def jwt_expiry(token: str | None) -> datetime | None:
    """Read the ``exp`` claim without verifying the signature (we are not the audience)."""
    if not token or token.count(".") != 2:
        return None
    payload_part = token.split(".")[1]
    try:
        padded = payload_part + "=" * (-len(payload_part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    except (KeyError, ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        return None


class SessionStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self._cookies: dict[str, str] = {}
        self._version = 0
        self._updated_at: datetime | None = None
        self._load()

    # ------------------------------------------------------------------ loading

    def _load(self) -> None:
        self._cookies = self._read_file()
        if self._cookies:
            logger.info("Loaded Vinted session from %s", self._settings.session_file)

    def _read_file(self) -> dict[str, str]:
        path = self._settings.session_file
        self._updated_at = None
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            logger.warning("Ignoring unreadable session file %s", path)
            return {}
        cookies = data.get("cookies")
        updated_raw = data.get("updated_at")
        if isinstance(updated_raw, str):
            try:
                self._updated_at = datetime.fromisoformat(updated_raw)
            except ValueError:
                pass
        return cookies if isinstance(cookies, dict) else {}

    def _persist(self) -> None:
        path = self._settings.session_file
        self._updated_at = datetime.now(tz=timezone.utc)
        payload: dict[str, Any] = {
            "cookies": self._cookies,
            "updated_at": self._updated_at.isoformat(timespec="seconds"),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".session-", suffix=".json")
            tmp_path = Path(tmp_name)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                os.replace(tmp_path, path)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
        except OSError:
            logger.exception("Could not persist Vinted session to %s", path)

    # ------------------------------------------------------------------- access

    @property
    def configured(self) -> bool:
        with self._lock:
            return bool(self._cookies)

    def snapshot(self) -> tuple[int, dict[str, str]]:
        with self._lock:
            return self._version, dict(self._cookies)

    def update(self, cookies: dict[str, str]) -> int:
        with self._lock:
            changed = {k: v for k, v in cookies.items() if v and self._cookies.get(k) != v}
            if not changed:
                return self._version
            self._cookies.update(changed)
            self._version += 1
            self._persist()
            return self._version

    def replace(self, cookies: dict[str, str]) -> int:
        """Overwrite the jar (used when seeding from a residential IP / pasted cookies)."""
        cleaned = {k: v for k, v in cookies.items() if k and v}
        with self._lock:
            self._cookies = cleaned
            self._version += 1
            self._persist()
            return self._version

    def has_access_token(self) -> bool:
        with self._lock:
            return bool(self._cookies.get(ACCESS_TOKEN_COOKIE))

    def access_token(self) -> str | None:
        with self._lock:
            return self._cookies.get(ACCESS_TOKEN_COOKIE)

    def clear(self) -> None:
        """Drop the cookie jar so the next poll bootstraps a brand new session."""
        with self._lock:
            self._cookies = {}
            self._version += 1
            self._persist()

    def access_token_expiry(self) -> datetime | None:
        with self._lock:
            return jwt_expiry(self._cookies.get(ACCESS_TOKEN_COOKIE))

    def refresh_token_expiry(self) -> datetime | None:
        with self._lock:
            return jwt_expiry(self._cookies.get(REFRESH_TOKEN_COOKIE))

    def status(self) -> dict[str, Any]:
        access_expiry = self.access_token_expiry()
        refresh_expiry = self.refresh_token_expiry()
        with self._lock:
            updated_at = self._updated_at
            cookie_count = len(self._cookies)
        return {
            "has_session": cookie_count > 0,
            "cookie_count": cookie_count,
            "access_expires_at": access_expiry.isoformat(timespec="seconds") if access_expiry else None,
            "access_expires_in_seconds": self.seconds_until_expiry(),
            "refresh_expires_at": refresh_expiry.isoformat(timespec="seconds") if refresh_expiry else None,
            "updated_at": updated_at.isoformat(timespec="seconds") if updated_at else None,
        }

    def seconds_until_expiry(self) -> float | None:
        expiry = self.access_token_expiry()
        if expiry is None:
            return None
        return (expiry - datetime.now(tz=timezone.utc)).total_seconds()

    def needs_refresh(self) -> bool:
        remaining = self.seconds_until_expiry()
        if remaining is None:
            return False
        return remaining <= self._settings.session_refresh_margin_seconds

    def needs_bootstrap(self) -> bool:
        """True when no HTTP refresh can save us — import cookies or run HTTP bootstrap."""
        if not self.has_access_token():
            return True
        refresh_expiry = self.refresh_token_expiry()
        if refresh_expiry is None:
            return not self.has_access_token()
        return refresh_expiry <= datetime.now(tz=timezone.utc)


_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = SessionStore()
        return _store
