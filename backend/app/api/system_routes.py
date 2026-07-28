"""Health, thread stats and a Telegram smoke test."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .. import telegram
from ..auth import require_admin
from ..config import Settings, get_settings
from ..models import MessageResponse, ThreadStats
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
