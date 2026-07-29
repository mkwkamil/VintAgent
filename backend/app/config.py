"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Admin
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
    # Comma-separated curl_cffi impersonation profiles (TLS + browser headers).
    vinted_impersonate: str = "chrome,chrome136,chrome142"
    # Optional residential proxy for ALL Vinted HTTP (refresh + scrape).
    # Example: http://user:pass@host:port  or  socks5h://user:pass@host:port
    vinted_proxy: str = ""
    # Renew access_token_web this many seconds before JWT expiry.
    session_refresh_margin_seconds: float = 1800.0
    # Also force a refresh this often even when the JWT is not near expiry yet.
    session_force_refresh_seconds: float = 2700.0

    # Chromium cookie bootstrap (optional; datacenter IPs usually fail CF).
    browser_bootstrap_enabled: bool = False
    browser_min_interval_seconds: float = 120.0
    browser_timeout_seconds: float = 90.0
    browser_executable_path: str = ""
    browser_locale: str = "pl-PL"
    browser_timezone: str = "Europe/Warsaw"
    session_check_interval_seconds: float = 60.0

    # Phone rescue: Telegram deep-link + one-time token (no admin login).
    public_base_url: str = ""
    session_rescue_ttl_seconds: float = 900.0
    session_rescue_alert_cooldown_seconds: float = 1800.0

    # Stats retention (hourly buckets).
    stats_retention_hours: int = 168

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Serving
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
