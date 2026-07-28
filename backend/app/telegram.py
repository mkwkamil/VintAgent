"""Telegram Bot API notifications.

Called from scraper threads, so every failure is swallowed and logged: a broken
notification must never take a polling thread down.
"""

from __future__ import annotations

import html
import logging
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


def format_item(item: "VintedItem", source_name: str) -> str:
    lines = [
        f"🆕 <b>{html.escape(item.title)}</b>",
        f"💰 {html.escape(item.price)}" if item.price else None,
        f"🏷 {html.escape(item.brand)}" if item.brand else None,
        f"📏 {html.escape(item.size)}" if item.size else None,
        f"🔍 {html.escape(source_name)}",
        f'\n<a href="{html.escape(item.url, quote=True)}">Zobacz na Vinted ↗</a>',
    ]
    return "\n".join(line for line in lines if line)


def send_item(item: "VintedItem", source_name: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    caption = format_item(item, source_name)
    keyboard = {"inline_keyboard": [[{"text": "Kup teraz ↗", "url": item.url}]]}

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
