"""Telegram Bot API notifications.

Called from scraper threads, so every failure is swallowed and logged: a broken
notification must never take a polling thread down.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from curl_cffi import requests as cffi

from .config import Settings, get_settings

if TYPE_CHECKING:
    from .scraper import VintedItem

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _post(method: str, payload: dict[str, Any], settings: Settings) -> bool:
    if not settings.telegram_enabled:
        logger.warning("Telegram is not configured; skipping %s", method)
        return False

    url = f"{API_BASE}/bot{settings.telegram_bot_token}/{method}"
    try:
        response = cffi.post(url, json=payload, timeout=settings.request_timeout_seconds)
    except Exception:
        logger.exception("Telegram request failed (%s)", method)
        return False

    if response.status_code >= 400:
        logger.error("Telegram %s returned %s: %s", method, response.status_code, response.text[:300])
        return False
    return True


def send_message(text: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return _post(
        "sendMessage",
        {
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        settings,
    )


def _join(parts: list[str], separator: str = " · ") -> str | None:
    filtered = [part for part in parts if part]
    return separator.join(filtered) if filtered else None


def format_item(item: "VintedItem", source_name: str) -> str:
    """Caption of a listing card: price first, then the details, then context."""
    esc = html.escape
    price_line = None
    if item.price:
        price_line = f"💰 <b>{esc(item.price)}</b>"
        if item.total_price:
            price_line += f" <i>(z ochroną {esc(item.total_price)})</i>"

    listed_at = None
    if item.listed_ts:
        listed_at = datetime.fromtimestamp(item.listed_ts, tz=timezone.utc).astimezone().strftime("%H:%M")

    lines = [
        f"🆕 <b>{esc(item.title)}</b>",
        price_line,
        _join([f"🏷 {esc(item.brand)}" if item.brand else "", f"📏 {esc(item.size)}" if item.size else ""]),
        f"✨ {esc(item.condition)}" if item.condition else None,
        "",
        _join([f"🔎 {esc(source_name)}", f"🕒 {listed_at}" if listed_at else ""]),
    ]
    return "\n".join(line for line in lines if line is not None)


def send_item(
    item: "VintedItem",
    source_name: str,
    settings: Settings | None = None,
    source_url: str | None = None,
) -> bool:
    settings = settings or get_settings()
    caption = format_item(item, source_name)
    buttons = [{"text": "🛒 Kup teraz", "url": item.url}]
    if source_url:
        buttons.append({"text": "🔎 Wyszukiwanie", "url": source_url})
    keyboard = {"inline_keyboard": [buttons]}

    if item.photo_url:
        sent = _post(
            "sendPhoto",
            {
                "chat_id": settings.telegram_chat_id,
                "photo": item.photo_url,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            settings,
        )
        if sent:
            return True
        logger.warning("sendPhoto failed for item %s, falling back to text", item.id)

    return _post(
        "sendMessage",
        {
            "chat_id": settings.telegram_chat_id,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "reply_markup": keyboard,
        },
        settings,
    )
