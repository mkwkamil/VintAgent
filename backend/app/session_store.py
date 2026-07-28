"""Shared Vinted cookie jar with persistence.

Vinted rotates *both* tokens on every refresh: the old refresh token dies the
moment a new one is issued. That makes the cookie set a single piece of shared
mutable state — every scraper thread must read from and write to this store, and
only one refresh may be in flight at a time (``refresh_lock``), otherwise threads
would invalidate each other's tokens.
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
        self._load()

    # ------------------------------------------------------------------ loading

    def _load(self) -> None:
        env_cookies = parse_cookie_header(self._settings.vinted_cookie)
        stored = self._read_file()

        # Whichever refresh token lives longer is the newer session: that way a
        # freshly pasted VINTED_COOKIE wins over a stale file, and a file written
        # by an earlier run wins over the by-now-expired value in .env.
        env_exp = jwt_expiry(env_cookies.get(REFRESH_TOKEN_COOKIE))
        stored_exp = jwt_expiry(stored.get(REFRESH_TOKEN_COOKIE))
        if stored and (env_exp is None or (stored_exp is not None and stored_exp > env_exp)):
            self._cookies = {**env_cookies, **stored}
            logger.info("Loaded Vinted session from %s", self._settings.session_file)
        else:
            self._cookies = {**stored, **env_cookies}
            if env_cookies:
                logger.info("Loaded Vinted session from VINTED_COOKIE")

    def _read_file(self) -> dict[str, str]:
        path = self._settings.session_file
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            logger.warning("Ignoring unreadable session file %s", path)
            return {}
        cookies = data.get("cookies")
        return cookies if isinstance(cookies, dict) else {}

    def _persist(self) -> None:
        path = self._settings.session_file
        payload: dict[str, Any] = {
            "cookies": self._cookies,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
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

    def access_token_expiry(self) -> datetime | None:
        with self._lock:
            return jwt_expiry(self._cookies.get(ACCESS_TOKEN_COOKIE))

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


_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = SessionStore()
        return _store
