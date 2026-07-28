"""Thread-safe persistence layer backed by a single JSON file.

Every mutation goes through :meth:`JsonStore.transaction`, which holds a reentrant
lock for the whole read-modify-write cycle and swaps the file in atomically, so
concurrent scraper threads can never interleave into a half-written file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import get_settings

logger = logging.getLogger(__name__)

STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


class JsonStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> dict[str, Any]:
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {"urls": []}
        except (json.JSONDecodeError, UnicodeDecodeError):
            corrupt = self._path.with_suffix(".corrupt.json")
            logger.error("data file is not valid JSON, moving it to %s", corrupt)
            os.replace(self._path, corrupt)
            return {"urls": []}

        if not isinstance(data, dict) or not isinstance(data.get("urls"), list):
            logger.error("data file has unexpected shape, starting from an empty state")
            return {"urls": []}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, prefix=".data-", suffix=".json")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            data = self._read()
            yield data
            self._write(data)


_store: JsonStore | None = None
_store_lock = threading.Lock()


def get_store() -> JsonStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = JsonStore(get_settings().data_file)
        return _store


def _find(data: dict[str, Any], url_id: str) -> dict[str, Any] | None:
    for record in data["urls"]:
        if record.get("id") == url_id:
            return record
    return None


def list_urls() -> list[dict[str, Any]]:
    return get_store().snapshot()["urls"]


def get_url(url_id: str) -> dict[str, Any] | None:
    return _find(get_store().snapshot(), url_id)


def create_url(name: str, url: str) -> dict[str, Any]:
    record = {
        "id": str(uuid.uuid4()),
        "name": name,
        "url": url,
        "status": STATUS_STOPPED,
        "created_at": utc_now(),
        "last_checked_at": None,
        "last_error": None,
        "seeded": False,
        "seen_ids": [],
    }
    with get_store().transaction() as data:
        data["urls"].append(record)
    return record


def update_url(url_id: str, *, name: str | None = None, url: str | None = None) -> dict[str, Any] | None:
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return None
        if name is not None:
            record["name"] = name
        if url is not None and url != record["url"]:
            # A different search means the previous baseline is meaningless; re-seed
            # on the next poll so the user is not flooded with pre-existing listings.
            record["url"] = url
            record["seeded"] = False
            record["seen_ids"] = []
            record["last_error"] = None
        return dict(record)


def delete_url(url_id: str) -> bool:
    with get_store().transaction() as data:
        remaining = [r for r in data["urls"] if r.get("id") != url_id]
        removed = len(remaining) != len(data["urls"])
        data["urls"] = remaining
        return removed


def set_status(url_id: str, status: str) -> dict[str, Any] | None:
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return None
        record["status"] = status
        if status == STATUS_STOPPED:
            record["last_error"] = None
        return dict(record)


def mark_checked(url_id: str, *, error: str | None = None) -> None:
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return
        record["last_checked_at"] = utc_now()
        record["last_error"] = error


def record_seen(url_id: str, item_ids: Iterable[int], *, seeded: bool = True) -> None:
    limit = get_settings().seen_ids_limit
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return
        known = list(record.get("seen_ids", []))
        known_set = set(known)
        for item_id in item_ids:
            if item_id not in known_set:
                known.append(item_id)
                known_set.add(item_id)
        record["seen_ids"] = known[-limit:]
        record["seeded"] = seeded
