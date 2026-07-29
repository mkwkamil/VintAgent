"""Telegram Bot API notifications and forum topics.

Called from scraper threads, so send failures are swallowed and logged: a broken
notification must never take a polling thread down. Creating/renaming topics
happens on the API request path, where errors can surface to the dashboard.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from curl_cffi import requests as cffi

from .config import Settings, get_settings

if TYPE_CHECKING:
    from .scraper import VintedItem

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
# Telegram forum topic names are capped at 128 characters.
TOPIC_NAME_MAX = 128
# Official Topics-set magnifying glass (🔎) from getForumTopicIconStickers.
TOPIC_ICON_SEARCH = "5309965701241379366"
# Light-blue topic colour (0x6FB9F0) — matches Telegram's default search style.
TOPIC_ICON_COLOR = 0x6FB9F0


def _call(
    method: str,
    payload: dict[str, Any] | None,
    settings: Settings,
    *,
    timeout: float | None = None,
) -> Any:
    if not settings.telegram_enabled:
        logger.warning("Telegram is not configured; skipping %s", method)
        return None

    url = f"{API_BASE}/bot{settings.telegram_bot_token}/{method}"
    try:
        response = cffi.post(
            url,
            json=payload or {},
            timeout=timeout or settings.request_timeout_seconds,
        )
    except Exception:
        logger.exception("Telegram request failed (%s)", method)
        return None

    try:
        body = response.json()
    except Exception:
        body = {}

    if response.status_code >= 400 or not body.get("ok"):
        logger.error(
            "Telegram %s returned %s: %s",
            method,
            response.status_code,
            (response.text or "")[:300],
        )
        return None
    return body.get("result")


def _post(method: str, payload: dict[str, Any], settings: Settings) -> bool:
    return _call(method, payload, settings) is not None


def _topic_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip()) or "Tracker"
    return cleaned[:TOPIC_NAME_MAX]


def create_forum_topic(name: str, settings: Settings | None = None) -> int | None:
    """Create a forum topic in the configured group. Returns ``message_thread_id``."""
    settings = settings or get_settings()
    result = _call(
        "createForumTopic",
        {
            "chat_id": settings.telegram_chat_id,
            "name": _topic_name(name),
            "icon_color": TOPIC_ICON_COLOR,
            "icon_custom_emoji_id": TOPIC_ICON_SEARCH,
        },
        settings,
    )
    if not isinstance(result, dict):
        return None
    thread_id = result.get("message_thread_id")
    try:
        return int(thread_id)
    except (TypeError, ValueError):
        logger.error("createForumTopic returned no message_thread_id: %s", result)
        return None


def rename_forum_topic(thread_id: int, name: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return _post(
        "editForumTopic",
        {
            "chat_id": settings.telegram_chat_id,
            "message_thread_id": thread_id,
            "name": _topic_name(name),
        },
        settings,
    )


def delete_forum_topic(thread_id: int, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return _post(
        "deleteForumTopic",
        {
            "chat_id": settings.telegram_chat_id,
            "message_thread_id": thread_id,
        },
        settings,
    )


def send_message(
    text: str,
    settings: Settings | None = None,
    *,
    message_thread_id: int | None = None,
) -> bool:
    settings = settings or get_settings()
    payload: dict[str, Any] = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    return _post("sendMessage", payload, settings)


def format_item(item: "VintedItem", _source_name: str = "") -> str:
    """English field labels; Quality value stays as returned by Vinted."""
    esc = html.escape
    lines: list[str] = [f"Title: <b>{esc(item.title)}</b>"]
    if item.brand:
        lines.append(f"Brand: <b>{esc(item.brand)}</b>")
    if item.size:
        lines.append(f"Size: <b>{esc(item.size)}</b>")
    if item.price:
        price_line = f"Price: <b>{esc(item.price)}</b>"
        if item.total_price:
            price_line += f" ({esc(item.total_price)})"
        lines.append(price_line)
    if item.condition:
        lines.append(f"Quality: <b>{esc(item.condition)}</b>")
    if item.listed_ts:
        listed_at = datetime.fromtimestamp(item.listed_ts, tz=timezone.utc).astimezone().strftime("%H:%M")
        lines.append(f"Posted: <b>{listed_at}</b>")
    return "\n".join(lines)


def _item_keyboard(item: "VintedItem", source_url: str | None) -> dict[str, Any]:
    row: list[dict[str, str]] = [{"text": "Buy now", "url": item.url}]
    if source_url:
        row.append({"text": "Search", "url": source_url})
    return {"inline_keyboard": [row]}


def send_item(
    item: "VintedItem",
    source_name: str,
    settings: Settings | None = None,
    source_url: str | None = None,
    *,
    message_thread_id: int | None = None,
) -> bool:
    settings = settings or get_settings()
    caption = format_item(item, source_name)
    keyboard = _item_keyboard(item, source_url)
    chat_id = settings.telegram_chat_id

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id

    if item.photo_url:
        result = _call("sendPhoto", {**payload, "photo": item.photo_url, "caption": caption}, settings)
        if result is not None:
            _unpin_sent(result, chat_id=chat_id, message_thread_id=message_thread_id, settings=settings)
            return True
        logger.warning("sendPhoto failed for item %s, falling back to text", item.id)

    result = _call(
        "sendMessage",
        {
            **payload,
            "text": caption,
            "disable_web_page_preview": False,
        },
        settings,
    )
    if result is not None:
        _unpin_sent(result, chat_id=chat_id, message_thread_id=message_thread_id, settings=settings)
        return True
    return False


def unpin_message(
    chat_id: str | int,
    message_id: int,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    return _post(
        "unpinChatMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": True,
        },
        settings,
    )


def clear_topic_pins(
    chat_id: str | int,
    message_thread_id: int | None,
    settings: Settings | None = None,
) -> bool:
    """Drop any pinned messages in a forum topic (new finds should not stay pinned)."""
    if message_thread_id is None:
        return False
    settings = settings or get_settings()
    return _post(
        "unpinAllForumTopicMessages",
        {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        },
        settings,
    )


def _unpin_sent(
    result: Any,
    *,
    chat_id: str | int,
    message_thread_id: int | None,
    settings: Settings,
) -> None:
    if isinstance(result, dict):
        message_id = result.get("message_id")
        if isinstance(message_id, int):
            unpin_message(chat_id, message_id, settings)
    elif isinstance(result, list):
        for entry in result:
            if isinstance(entry, dict) and isinstance(entry.get("message_id"), int):
                unpin_message(chat_id, entry["message_id"], settings)
    clear_topic_pins(chat_id, message_thread_id, settings)
