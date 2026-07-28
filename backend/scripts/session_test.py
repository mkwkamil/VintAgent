"""Offline checks for the shared Vinted session store and its auto-renewal.

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

from app import browser_session  # noqa: E402
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


def cookies_for(access_hours: float, refresh_hours: float) -> dict[str, str]:
    return {
        "access_token_web": fake_jwt(access_hours),
        "refresh_token_web": fake_jwt(refresh_hours),
        "anon_id": "abc",
    }


tmp = Path(tempfile.mkdtemp(prefix="vintagent-session-"))


def settings_for(name: str = "session.json", margin: float = 600.0) -> Settings:
    return Settings(
        session_file=tmp / name,
        session_refresh_margin_seconds=margin,
        _env_file=None,
    )


def store_with(cookies: dict[str, str], name: str = "session.json") -> SessionStore:
    """Seed a store the way the browser bootstrap would."""
    settings = settings_for(name)
    settings.session_file.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    return SessionStore(settings)


# --- expiry parsing -----------------------------------------------------------
check("jwt_expiry reads the exp claim", jwt_expiry(fake_jwt(2)) is not None)
check("jwt_expiry tolerates junk", jwt_expiry("not-a-jwt") is None)

# --- freshness ----------------------------------------------------------------
fresh = store_with(cookies_for(2, 168), "fresh.json")
check("a 2h-old token is not due for refresh", not fresh.needs_refresh())
check("a valid session needs no browser", not fresh.needs_bootstrap())

stale = store_with(cookies_for(0.05, 168), "stale.json")
check("a token expiring in 3 min is due for refresh", stale.needs_refresh())
check("an HTTP refresh is still possible", not stale.needs_bootstrap())

dead = store_with(cookies_for(-2, -1), "dead.json")
check("an expired refresh token forces a browser bootstrap", dead.needs_bootstrap())
check("an empty store forces a browser bootstrap", SessionStore(settings_for("empty.json")).needs_bootstrap())

# --- persistence --------------------------------------------------------------
rotated = cookies_for(2, 168)
version_before = stale.snapshot()[0]
version_after = stale.update(rotated)
check("update bumps the version", version_after > version_before, (version_before, version_after))
check("rotated tokens land on disk", (tmp / "stale.json").is_file())
check("refreshed store is no longer stale", not stale.needs_refresh())
mode = oct((tmp / "stale.json").stat().st_mode & 0o777)
check("session file is owner-only", mode == "0o600", mode)

reloaded = SessionStore(settings_for("stale.json"))
check(
    "a restart reuses the tokens written by the previous run",
    reloaded.snapshot()[1]["refresh_token_web"] == rotated["refresh_token_web"],
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


shared_store = store_with(cookies_for(0.05, 168), "shared.json")
shared_settings = settings_for("shared.json")
fake_session = FakeSession()

scrapers = []
for _ in range(6):
    scraper = VintedScraper(shared_settings)
    scraper._store = shared_store
    scraper._session = fake_session
    scrapers.append(scraper)

results: list[bool] = []
threads = [threading.Thread(target=lambda s=s: results.append(s._refresh_access_token())) for s in scrapers]
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

# --- browser fallback ---------------------------------------------------------
class RecordingBootstrap:
    def __init__(self) -> None:
        self.calls = 0

    def ensure_session(self, *, force: bool = False) -> bool:
        self.calls += 1
        return True

    def status(self) -> dict[str, object]:
        return {"browser_available": True, "last_bootstrap_at": None, "last_bootstrap_error": None}


recording = RecordingBootstrap()
browser_session._bootstrap = recording  # type: ignore[assignment]

dead_store = store_with(cookies_for(-2, -1), "dead-renew.json")
renewing = VintedScraper(settings_for("dead-renew.json"))
renewing._store = dead_store
renewing._session = FakeSession()
check("a dead session falls back to the browser", renewing.renew_session())
check("the browser was asked exactly once", recording.calls == 1, recording.calls)

recording.calls = 0
healthy = VintedScraper(shared_settings)
healthy._store = shared_store
healthy._session = FakeSession()
healthy.renew_session()
check("a healthy session never launches the browser", recording.calls == 0, recording.calls)

# The rate limiter must survive a burst of failures without spawning browsers.
real = browser_session.BrowserBootstrap(settings_for("ratelimit.json"))
real._available = True
real._collect_cookies = lambda: {}  # type: ignore[method-assign]
first = real.ensure_session()
second = real.ensure_session()
check("a bootstrap without a token reports failure", not first)
check("a retry is blocked by the minimum interval", not second)

print()
print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
