"""Health, thread stats, session import and a Telegram smoke test."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .. import telegram
from ..auth import require_admin
from ..config import Settings, get_settings
from ..models import MessageResponse, SessionImport, SessionStatus, ThreadStats
from ..session_manager import get_session_manager
from ..session_store import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, parse_cookie_header
from ..storage import STATUS_RUNNING, list_urls
from ..thread_manager import get_manager

router = APIRouter(tags=["system"])


def _scraping_status() -> tuple[bool, str | None]:
    for record in list_urls():
        if record.get("status") != STATUS_RUNNING:
            continue
        error = record.get("last_error")
        if error:
            return True, str(error)
    return False, None


def _session_status() -> SessionStatus:
    return SessionStatus(**get_session_manager().status())


def _cookies_from_import(payload: SessionImport) -> dict[str, str]:
    raw = (payload.cookie or "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wklej nagłówek Cookie z przeglądarki (DevTools → Network → Cookie)",
        )
    cookies = parse_cookie_header(raw)
    if ACCESS_TOKEN_COOKIE not in cookies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Brak access_token_web w Cookie")
    if REFRESH_TOKEN_COOKIE not in cookies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Brak refresh_token_web — skopiuj cały nagłówek Cookie",
        )
    return cookies


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    from .. import __version__

    return {"status": "ok", "version": __version__}


@router.get("/stats", response_model=ThreadStats)
def stats(
    _: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> ThreadStats:
    manager = get_manager()
    blocked, error = _scraping_status()
    return ThreadStats(
        active_threads=manager.active_count(),
        max_threads=manager.max_threads,
        telegram_enabled=settings.telegram_enabled,
        scraping_blocked=blocked,
        scraping_error=error,
    )


@router.get("/session", response_model=SessionStatus)
def session_status(_: str = Depends(require_admin)) -> SessionStatus:
    return _session_status()


@router.post("/session/refresh", response_model=SessionStatus)
def session_refresh(_: str = Depends(require_admin)) -> SessionStatus:
    if not get_session_manager().recover():
        detail = get_session_manager().status().get("last_bootstrap_error") or "Nie udało się odnowić sesji"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    return _session_status()


@router.post("/session/import", response_model=SessionStatus)
def session_import(payload: SessionImport, _: str = Depends(require_admin)) -> SessionStatus:
    cookies = _cookies_from_import(payload)
    get_session_manager().push_manual_cookies(cookies)
    return _session_status()


@router.post("/telegram/test", response_model=MessageResponse)
def telegram_test(
    _: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    if not settings.telegram_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Brak TELEGRAM_BOT_TOKEN lub TELEGRAM_CHAT_ID w .env",
        )
    if not telegram.send_message("✅ VintAgent: test połączenia z Telegramem", settings):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nie udało się wysłać wiadomości, sprawdź token i chat ID",
        )
    return MessageResponse(detail="Wiadomość testowa wysłana")
