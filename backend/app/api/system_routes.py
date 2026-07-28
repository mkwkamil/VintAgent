"""Health, thread stats and a Telegram smoke test."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .. import telegram
from ..auth import require_admin
from ..browser_session import get_bootstrap
from ..config import Settings, get_settings
from ..models import MessageResponse, SessionImport, SessionStatus, ThreadStats
from ..session_store import ACCESS_TOKEN_COOKIE, get_session_store, parse_cookie_header
from ..thread_manager import get_manager

router = APIRouter(tags=["system"])


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
    return ThreadStats(
        active_threads=manager.active_count(),
        max_threads=manager.max_threads,
        telegram_enabled=settings.telegram_enabled,
    )


@router.get("/session", response_model=SessionStatus)
def session_status(_: str = Depends(require_admin)) -> SessionStatus:
    return SessionStatus(**get_session_store().status(), **get_bootstrap().status())


@router.post("/session/refresh", response_model=SessionStatus)
def session_refresh(_: str = Depends(require_admin)) -> SessionStatus:
    """Force a browser bootstrap; the polling threads pick the cookies up on their next request."""
    bootstrap = get_bootstrap()
    if not bootstrap.status()["browser_available"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Automatyczne odnawianie sesji jest niedostępne (brak Chromium)",
        )
    if not bootstrap.ensure_session(force=True):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=bootstrap.status()["last_bootstrap_error"] or "Nie udało się odnowić sesji Vinted",
        )
    return SessionStatus(**get_session_store().status(), **bootstrap.status())


@router.post("/session/import", response_model=SessionStatus)
def session_import(payload: SessionImport, _: str = Depends(require_admin)) -> SessionStatus:
    """Seed the jar with cookies from a residential browser.

    Datacenter IPs (GCP Free Tier) are often refused a Cloudflare challenge, so
    the practical workaround is to bootstrap once on a home machine and paste
    the Cookie header (or copy session.json) onto the server. HTTP refresh then
    keeps the session alive for weeks.
    """
    cookies = parse_cookie_header(payload.cookie)
    if ACCESS_TOKEN_COOKIE not in cookies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Brak access_token_web w cookies — skopiuj cały nagłówek Cookie z vinted.pl",
        )
    get_session_store().replace(cookies)
    return SessionStatus(**get_session_store().status(), **get_bootstrap().status())


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
