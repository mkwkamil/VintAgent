"""Tracked URL management (the only thing the dashboard talks to)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .. import analytics, storage
from ..auth import require_admin
from ..models import MessageResponse, URLCreate, URLOut, URLStats, URLUpdate
from ..storage import STATUS_RUNNING, STATUS_STOPPED
from ..thread_manager import MaxThreadsReached, get_manager

router = APIRouter(prefix="/urls", tags=["urls"], dependencies=[Depends(require_admin)])


def _out(record: dict) -> URLOut:
    return URLOut.from_record(record, thread_alive=get_manager().is_running(record["id"]))


def _require_record(url_id: str) -> dict:
    record = storage.get_url(url_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono URL-a")
    return record


@router.get("", response_model=list[URLOut])
def list_urls() -> list[URLOut]:
    return [_out(record) for record in storage.list_urls()]


@router.get("/{url_id}", response_model=URLOut)
def get_url(url_id: str) -> URLOut:
    return _out(_require_record(url_id))


@router.get("/{url_id}/stats", response_model=URLStats)
def url_stats(
    url_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    tz_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> URLStats:
    record = _require_record(url_id)
    return URLStats(**analytics.detail(record, tz_offset_minutes=tz_offset_minutes, hours=hours))


@router.post("/{url_id}/stats/reset", response_model=MessageResponse)
def reset_url_stats(url_id: str) -> MessageResponse:
    _require_record(url_id)
    storage.reset_stats(url_id)
    return MessageResponse(detail="Statystyki wyczyszczone")


@router.post("", response_model=URLOut, status_code=status.HTTP_201_CREATED)
def create_url(payload: URLCreate) -> URLOut:
    return _out(storage.create_url(payload.name, payload.url))


@router.patch("/{url_id}", response_model=URLOut)
def update_url(url_id: str, payload: URLUpdate) -> URLOut:
    _require_record(url_id)
    updated = storage.update_url(url_id, name=payload.name, url=payload.url)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nie znaleziono URL-a")

    # A running thread caches nothing but the id, yet restarting makes the new
    # search take effect immediately instead of on the next poll.
    manager = get_manager()
    if payload.url is not None and manager.is_running(url_id):
        manager.restart(url_id)
    return _out(updated)


@router.delete("/{url_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_url(url_id: str) -> Response:
    _require_record(url_id)
    get_manager().stop(url_id)
    storage.delete_url(url_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{url_id}/start", response_model=URLOut)
def start_url(url_id: str) -> URLOut:
    _require_record(url_id)
    try:
        get_manager().start(url_id)
    except MaxThreadsReached as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    storage.set_status(url_id, STATUS_RUNNING)
    return _out(_require_record(url_id))


@router.post("/{url_id}/stop", response_model=URLOut)
def stop_url(url_id: str) -> URLOut:
    _require_record(url_id)
    get_manager().stop(url_id)
    storage.set_status(url_id, STATUS_STOPPED)
    return _out(_require_record(url_id))
