"""Pydantic request/response schemas.

``URLOut`` deliberately omits ``seen_ids`` and every scraped listing detail: the
dashboard is a URL manager only, scraped items go to Telegram exclusively.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

URLStatus = Literal["running", "stopped"]


def _validate_url(value: str) -> str:
    value = value.strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("URL musi zaczynać się od http:// lub https://")
    if "vinted." not in value:
        raise ValueError("URL musi wskazywać na domenę Vinted")
    return value


class URLCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=10, max_length=2000)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return _validate_url(value)


class URLUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    url: str | None = Field(default=None, min_length=10, max_length=2000)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value)


class StatsSummary(BaseModel):
    found_total: int = 0
    found_last_hour: int = 0
    found_last_24h: int = 0
    checks: int = 0
    errors: int = 0
    error_rate: float = 0.0
    found_per_hour: float = 0.0
    last_found_at: str | None = None


class URLOut(BaseModel):
    id: str
    name: str
    url: str
    status: URLStatus
    created_at: str
    last_checked_at: str | None = None
    last_error: str | None = None
    thread_alive: bool = False
    telegram_topic_id: int | None = None
    stats: StatsSummary = StatsSummary()

    @classmethod
    def from_record(cls, record: dict[str, Any], *, thread_alive: bool) -> "URLOut":
        from .analytics import summarize

        topic = record.get("telegram_topic_id")
        try:
            topic_id = int(topic) if topic is not None else None
        except (TypeError, ValueError):
            topic_id = None

        return cls(
            id=record["id"],
            name=record["name"],
            url=record["url"],
            status=record.get("status", "stopped"),
            created_at=record.get("created_at", ""),
            last_checked_at=record.get("last_checked_at"),
            last_error=record.get("last_error"),
            thread_alive=thread_alive,
            telegram_topic_id=topic_id,
            stats=StatsSummary(**summarize(record)),
        )


class TimelinePoint(BaseModel):
    hour: str
    count: int


class URLStats(BaseModel):
    summary: StatsSummary
    found_timeline: list[TimelinePoint]
    listed_by_hour_of_day: list[int]
    found_by_hour_of_day: list[int]
    timeline_hours: int


class SessionStatus(BaseModel):
    has_session: bool
    cookie_count: int = 0
    access_expires_at: str | None = None
    access_expires_in_seconds: float | None = None
    refresh_expires_at: str | None = None
    updated_at: str | None = None
    browser_available: bool = False
    browser_running: bool = False
    cdp_ok: bool = False
    proxy_configured: bool = False
    last_bootstrap_at: str | None = None
    last_bootstrap_error: str | None = None


class SessionImport(BaseModel):
    """Emergency manual seed — paste full Cookie header from DevTools."""

    cookie: str = Field(min_length=20, max_length=32_000)


class ThreadStats(BaseModel):
    active_threads: int
    max_threads: int
    telegram_enabled: bool
    scraping_blocked: bool = False
    scraping_error: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class MessageResponse(BaseModel):
    detail: str
