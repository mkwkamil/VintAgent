"""Health, thread stats, session import/rescue and a Telegram smoke test."""

from __future__ import annotations

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from .. import telegram
from ..auth import require_admin
from ..browser_session import get_bootstrap
from ..config import Settings, get_settings
from ..models import MessageResponse, RescueStatus, SessionImport, SessionStatus, ThreadStats
from ..session_rescue import get_session_rescue, notify_session_rescued
from ..session_store import ACCESS_TOKEN_COOKIE, get_session_store, parse_cookie_header
from ..storage import STATUS_RUNNING, list_urls
from ..thread_manager import get_manager

router = APIRouter(tags=["system"])


def _scraping_status() -> tuple[bool, str | None]:
    """True when a running tracker recently failed to reach Vinted (not the dashboard)."""
    for record in list_urls():
        if record.get("status") != STATUS_RUNNING:
            continue
        error = record.get("last_error")
        if error:
            return True, str(error)
    return False, None


def _apply_cookies(raw: str) -> SessionStatus:
    cookies = parse_cookie_header(raw)
    if ACCESS_TOKEN_COOKIE not in cookies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Brak access_token_web w cookies — otwórz vinted.pl w przeglądarce i wyślij ponownie",
        )
    get_session_store().replace(cookies)
    notify_session_rescued()
    return SessionStatus(**get_session_store().status(), **get_bootstrap().status())


def _rescue_html(title: str, body: str, redirect: str) -> HTMLResponse:
    import html as html_lib

    safe_redirect = redirect.replace('"', "")
    safe_body = html_lib.escape(body)
    safe_title = html_lib.escape(title)
    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="1;url={safe_redirect}" />
  <title>{safe_title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0a0a0a; color: #f5f5f5;
           display: grid; min-height: 100vh; place-items: center; margin: 0; padding: 1.5rem; }}
    p {{ max-width: 28rem; line-height: 1.5; text-align: center; }}
    a {{ color: #60a5fa; }}
  </style>
</head>
<body>
  <p>{safe_body}<br /><a href="{safe_redirect}">Kontynuuj</a></p>
</body>
</html>"""
    return HTMLResponse(html)


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
    """Seed the jar with cookies from a residential browser (admin JWT)."""
    return _apply_cookies(payload.cookie)


@router.post("/session/rescue/test", response_model=MessageResponse)
def session_rescue_test(_: str = Depends(require_admin)) -> MessageResponse:
    """Force a rescue Telegram alert (ignores cooldown) for setup checks."""
    from ..session_rescue import notify_session_rescue_needed

    get_session_rescue().reset_alert_gate()
    if not notify_session_rescue_needed("Test alertu ratunkowego — możesz zignorować, jeśli tylko sprawdzasz."):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nie udało się wysłać alertu — sprawdź Telegram i PUBLIC_BASE_URL",
        )
    return MessageResponse(detail="Wysłano testowy alert ratunkowy na Telegram")


@router.get("/session/rescue/{token}", response_model=RescueStatus)
def session_rescue_status(token: str) -> RescueStatus:
    payload = get_session_rescue().status_payload(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Link wygasł lub został już użyty — poczekaj na nowy alert Telegram",
        )
    return RescueStatus(**payload)


@router.post("/session/rescue/{token}", response_model=SessionStatus)
def session_rescue_import(token: str, payload: SessionImport) -> SessionStatus:
    """Public one-time import (phone rescue). No admin JWT."""
    if get_session_rescue().peek(token) is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Link wygasł lub został już użyty — poczekaj na nowy alert Telegram",
        )
    status_out = _apply_cookies(payload.cookie)
    get_session_rescue().consume(token)
    return status_out


@router.post("/session/rescue/{token}/form", response_class=HTMLResponse)
async def session_rescue_form(token: str, request: Request) -> HTMLResponse:
    """Bookmarklet target: form POST avoids CORS / mixed-content fetch issues."""
    rescue = get_session_rescue()
    if rescue.peek(token) is None:
        return _rescue_html(
            "Link wygasł",
            "Ten link ratunkowy wygasł lub został już użyty.",
            "/#/rescue?err=expired",
        )
    body = (await request.body()).decode("utf-8", errors="replace")
    cookie = (parse_qs(body).get("cookie") or [""])[0]
    try:
        _apply_cookies(cookie)
        rescue.consume(token)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Nie udało się zapisać cookies"
        return _rescue_html(
            "Błąd",
            detail,
            f"/#/rescue?t={token}&err=missing",
        )
    return _rescue_html(
        "Sesja OK",
        "Cookies zapisane. Scraping wraca do pracy.",
        "/#/rescue?ok=1",
    )


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
