"""One-time session rescue tokens and Telegram alerts.

When HTTP refresh can no longer keep the Vinted jar alive, operators get a
Telegram message with a deep link. Opening it on a phone (residential IP) lets
them push fresh cookies via bookmarklet or paste — no admin login required.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class RescueToken:
    token: str
    created_at: float
    expires_at: float
    reason: str
    used: bool = False


class SessionRescue:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.Lock()
        self._tokens: dict[str, RescueToken] = {}
        self._last_alert_at = 0.0
        self._pending = False

    def _purge_locked(self, now: float) -> None:
        dead = [key for key, item in self._tokens.items() if item.used or item.expires_at <= now]
        for key in dead:
            del self._tokens[key]

    def create_token(self, reason: str) -> RescueToken:
        settings = self._settings
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            item = RescueToken(
                token=secrets.token_urlsafe(24),
                created_at=now,
                expires_at=now + settings.session_rescue_ttl_seconds,
                reason=reason,
            )
            self._tokens[item.token] = item
            return item

    def peek(self, token: str) -> RescueToken | None:
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            item = self._tokens.get(token)
            if item is None or item.used or item.expires_at <= now:
                return None
            return item

    def consume(self, token: str) -> RescueToken | None:
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            item = self._tokens.get(token)
            if item is None or item.used or item.expires_at <= now:
                return None
            item.used = True
            self._pending = False
            return item

    def mark_rescued(self) -> bool:
        """Clear pending alert state. Returns True if an alert was outstanding."""
        with self._lock:
            was_pending = self._pending
            self._pending = False
            for item in self._tokens.values():
                item.used = True
            return was_pending

    def should_alert(self) -> bool:
        settings = self._settings
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            if now - self._last_alert_at < settings.session_rescue_alert_cooldown_seconds:
                return False
            # Re-alert if previous token already expired while still pending.
            active = any(not item.used and item.expires_at > now for item in self._tokens.values())
            if active and self._pending:
                return False
            return True

    def reset_alert_gate(self) -> None:
        """Allow the next notify_session_rescue_needed call to send immediately."""
        with self._lock:
            self._last_alert_at = 0.0
            self._pending = False

    def record_alert_sent(self) -> None:
        with self._lock:
            self._last_alert_at = time.time()
            self._pending = True

    def rescue_url(self, token: str) -> str | None:
        base = self._settings.public_base_url.rstrip("/")
        if not base:
            return None
        return f"{base}/#/rescue?t={quote(token)}"

    def bookmarklet(self, token: str) -> str | None:
        """Navigate-away form POST — works even when VintAgent is plain HTTP."""
        base = self._settings.public_base_url.rstrip("/")
        if not base:
            return None
        action = f"{base}/api/session/rescue/{token}/form"
        # Collect document.cookie plus any token-looking localStorage values.
        return (
            "javascript:void(function(){"
            f"var a={action!r},c=document.cookie||'';"
            "try{for(var i=0;i<localStorage.length;i++){"
            "var k=localStorage.key(i),v=localStorage.getItem(k)||'';"
            "if(/access_token|refresh_token/i.test(k+' '+v))c+='; '+k+'='+v;"
            "}}catch(e){}"
            "if(!c||c.length<20){alert('Brak cookies na tej stronie. Upewnij się, że jesteś na vinted.pl');return;}"
            "var f=document.createElement('form');f.method='POST';f.action=a;"
            "var i=document.createElement('input');i.type='hidden';i.name='cookie';i.value=c;"
            "f.appendChild(i);document.body.appendChild(f);f.submit();"
            "}())"
        )

    def status_payload(self, token: str) -> dict[str, Any] | None:
        item = self.peek(token)
        if item is None:
            return None
        remaining = max(0, int(item.expires_at - time.time()))
        return {
            "valid": True,
            "expires_in_seconds": remaining,
            "reason": item.reason,
            "vinted_url": self._settings.vinted_base_url.rstrip("/"),
            "public_base_url": self._settings.public_base_url.rstrip("/") or None,
            "bookmarklet": self.bookmarklet(token),
        }


_rescue: SessionRescue | None = None
_rescue_lock = threading.Lock()


def get_session_rescue() -> SessionRescue:
    global _rescue
    with _rescue_lock:
        if _rescue is None:
            _rescue = SessionRescue()
        return _rescue


def notify_session_rescue_needed(reason: str) -> bool:
    """Create a rescue token and ping Telegram (rate-limited). Returns True if sent."""
    settings = get_settings()
    rescue = get_session_rescue()
    if not rescue.should_alert():
        return False

    item = rescue.create_token(reason)
    url = rescue.rescue_url(item.token)

    from . import telegram

    lines = [
        "<b>VintAgent: sesja Vinted padła</b>",
        html_escape_reason(reason),
        "",
        "Otwórz link na telefonie (LTE / Wi‑Fi domowe), wejdź na vinted.pl",
        "i wyślij cookies zakładką albo wklej nagłówek Cookie.",
    ]
    if url:
        lines.append("")
        lines.append(f'<a href="{url}">Odnów sesję</a>')
    else:
        lines.append("")
        lines.append(
            "Ustaw PUBLIC_BASE_URL w .env (np. http://IP:8000), "
            "albo użyj Wklej w panelu."
        )

    keyboard = None
    if url:
        keyboard = {"inline_keyboard": [[{"text": "Odnów sesję", "url": url}]]}

    ok = telegram.send_message("\n".join(lines), settings, reply_markup=keyboard)
    if ok:
        rescue.record_alert_sent()
        logger.warning("Session rescue alert sent (%s)", reason)
    else:
        logger.error("Failed to send session rescue alert")
    return ok


def notify_session_rescued() -> None:
    rescue = get_session_rescue()
    was_pending = rescue.mark_rescued()
    if not was_pending:
        return
    settings = get_settings()
    from . import telegram

    telegram.send_message(
        "<b>VintAgent: sesja Vinted OK</b>\nCookies zaktualizowane — scraping wraca do normalnej pracy.",
        settings,
    )


def html_escape_reason(reason: str) -> str:
    import html

    return html.escape(reason.strip() or "Wymagane ręczne odnowienie sesji.")
