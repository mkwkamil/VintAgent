"""Offline checks for the shared Vinted session store and token auto-refresh.

    python scripts/session_test.py
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.scraper import VintedScraper  # noqa: E402
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


def cookie_header(access_hours: float, refresh_hours: float) -> str:
    return f"access_token_web={fake_jwt(access_hours)}; refresh_token_web={fake_jwt(refresh_hours)}; anon_id=abc"


tmp = Path(tempfile.mkdtemp(prefix="vintagent-session-"))


def settings_for(cookie: str, margin: float = 600.0) -> Settings:
    return Settings(
        vinted_cookie=cookie,
        session_file=tmp / "session.json",
        session_refresh_margin_seconds=margin,
        _env_file=None,
    )


# --- expiry parsing -----------------------------------------------------------
check("jwt_expiry reads the exp claim", jwt_expiry(fake_jwt(2)) is not None)
check("jwt_expiry tolerates junk", jwt_expiry("not-a-jwt") is None)

# --- freshness ----------------------------------------------------------------
fresh = SessionStore(settings_for(cookie_header(2, 168)))
check("a 2h-old token is not due for refresh", not fresh.needs_refresh())
stale = SessionStore(settings_for(cookie_header(0.05, 168)))
check("a token expiring in 3 min is due for refresh", stale.needs_refresh())

# --- persistence --------------------------------------------------------------
rotated = cookie_header(2, 168)
new_cookies = {k: v for k, v in (c.strip().split("=", 1) for c in rotated.split(";"))}
version_before = stale.snapshot()[0]
version_after = stale.update(new_cookies)
check("update bumps the version", version_after > version_before, (version_before, version_after))
check("rotated tokens land on disk", (tmp / "session.json").is_file())
check("refreshed store is no longer stale", not stale.needs_refresh())
mode = oct((tmp / "session.json").stat().st_mode & 0o777)
check("session file is owner-only", mode == "0o600", mode)

# --- precedence between .env and the persisted file ---------------------------
reloaded = SessionStore(settings_for(cookie_header(0.05, 1)))
check(
    "the longer-lived refresh token wins on load",
    jwt_expiry(reloaded.snapshot()[1]["refresh_token_web"]) == jwt_expiry(new_cookies["refresh_token_web"]),
)
pasted = cookie_header(2, 500)
fresh_paste = SessionStore(settings_for(pasted))
check(
    "a freshly pasted VINTED_COOKIE overrides the old file",
    jwt_expiry(fresh_paste.snapshot()[1]["refresh_token_web"]) > jwt_expiry(new_cookies["refresh_token_web"]),
)

# --- single-flight refresh under concurrency ----------------------------------
class FakeCookies(dict):
    def set(self, name, value, domain="", path="/", secure=False):
        self[name] = value

    def items(self):
        return dict.items(self)


class FakeResponse:
    status_code = 200


class FakeSession:
    """Stands in for curl_cffi: counts refresh calls and rotates the tokens."""

    def __init__(self) -> None:
        self.cookies = FakeCookies()
        self.calls = 0

    def post(self, url, headers=None, timeout=None):
        self.calls += 1
        time.sleep(0.05)  # widen the window for a race
        self.cookies["access_token_web"] = fake_jwt(2)
        self.cookies["refresh_token_web"] = fake_jwt(168)
        return FakeResponse()


shared_settings = settings_for(cookie_header(0.05, 168))
shared_store = SessionStore(shared_settings)
fake_session = FakeSession()

scrapers = []
for _ in range(6):
    scraper = VintedScraper(shared_settings)
    scraper._store = shared_store
    scraper._session = fake_session
    scrapers.append(scraper)

results: list[bool] = []
threads = [
    threading.Thread(target=lambda s=s: results.append(s._refresh_access_token())) for s in scrapers
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()

check("6 concurrent threads trigger exactly one refresh", fake_session.calls == 1, fake_session.calls)
check("every thread reports success", all(results) and len(results) == 6, results)
check("store is fresh after the refresh", not shared_store.needs_refresh())
check(
    "all scrapers converge on the same cookie version",
    len({s._cookie_version for s in scrapers}) == 1,
    [s._cookie_version for s in scrapers],
)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
