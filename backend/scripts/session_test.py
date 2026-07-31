"""Offline checks for session store + CDP helpers (bez Chrome)."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.session_manager import SessionManager, impersonate_for_ua  # noqa: E402
from app.session_store import SessionStore, jwt_expiry  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if not condition else ""))
    if not condition:
        failures.append(label)


def fake_jwt(hours_from_now: float) -> str:
    exp = int((datetime.now(tz=timezone.utc) + timedelta(hours=hours_from_now)).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def cookies_for(access_hours: float, refresh_hours: float) -> dict[str, str]:
    return {
        "access_token_web": fake_jwt(access_hours),
        "refresh_token_web": fake_jwt(refresh_hours),
        "anon_id": "abc",
    }


tmp = Path(tempfile.mkdtemp(prefix="vintagent-session-"))


def settings_for(name: str = "session.json") -> Settings:
    return Settings(
        session_file=tmp / name,
        browser_profile_dir=tmp / "chrome_cdp",
        browser_bootstrap_enabled=False,
        _env_file=None,
    )


def store_with(cookies: dict[str, str], name: str = "session.json") -> SessionStore:
    settings = settings_for(name)
    settings.session_file.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    return SessionStore(settings)


check("jwt_expiry", jwt_expiry(fake_jwt(2)) is not None)
fresh = store_with(cookies_for(2, 168))
check("fresh not due", not fresh.needs_refresh())
check("impersonate chrome142", impersonate_for_ua("Chrome/142.0.0.0", ["chrome", "chrome142"]) == "chrome142")

manager = SessionManager(settings_for("mgr.json"))
with patch("app.session_manager.get_session_store", return_value=fresh):
    check("ensure_ready with valid jar", manager.ensure_ready())

manager.push_manual_cookies(cookies_for(2, 168))
with patch("app.session_manager.get_session_store", return_value=fresh):
    manager.push_manual_cookies(cookies_for(3, 168))
    check("manual push", fresh.has_access_token())

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
