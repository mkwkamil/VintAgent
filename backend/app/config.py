"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Admin login
    admin_username: str = "admin"
    admin_password: str = "change-me"
    jwt_secret: str = "change-me-long-random-secret"
    jwt_expire_hours: int = 168

    # Scraper
    max_threads: int = 10
    poll_min_seconds: float = 10.0
    poll_max_seconds: float = 15.0
    blocked_backoff_min_seconds: float = 60.0
    blocked_backoff_max_seconds: float = 180.0
    error_backoff_seconds: float = 30.0
    request_timeout_seconds: float = 20.0
    items_per_page: int = 24
    seen_ids_limit: int = 300
    vinted_base_url: str = "https://www.vinted.pl"
    # curl_cffi impersonation profiles, rotated per session. Each profile ships a
    # matching TLS fingerprint AND browser headers, so the User-Agent must come
    # from the profile rather than being overridden by hand.
    vinted_impersonate: str = "chrome,chrome136,chrome142"
    # Vinted access tokens live 2h and refresh tokens 7 days, both rotating on
    # every refresh; renew this many seconds before expiry.
    session_refresh_margin_seconds: float = 600.0

    # Headless Chromium fallback: the only way past a Cloudflare JS challenge.
    # It runs on demand (missing or dead session), not on a schedule, so the
    # steady-state memory cost is zero.
    browser_bootstrap_enabled: bool = True
    browser_min_interval_seconds: float = 120.0
    browser_timeout_seconds: float = 45.0
    browser_executable_path: str = ""
    browser_locale: str = "pl-PL"
    browser_timezone: str = "Europe/Warsaw"
    # How often the watchdog verifies the session is still good.
    session_check_interval_seconds: float = 300.0

    # Per-URL statistics: hourly buckets, kept for a week.
    stats_retention_hours: int = 168

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # API / serving
    cors_origins: str = "*"
    data_file: Path = BACKEND_DIR / "data" / "data.json"
    session_file: Path = BACKEND_DIR / "data" / "session.json"
    static_dir: Path = BACKEND_DIR / "static"

    @property
    def impersonate_profiles(self) -> list[str]:
        return [p.strip() for p in self.vinted_impersonate.split(",") if p.strip()] or ["chrome"]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
