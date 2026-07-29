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


def hour_key(moment: datetime) -> str:
    """Hourly bucket id in UTC, e.g. ``2026-07-28T21``."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def empty_stats() -> dict[str, Any]:
    return {
        # Keyed by hour: "found" is what we detected, "listed" is when the seller
        # actually posted it. Two different questions, two different histograms.
        "found_by_hour": {},
        "listed_by_hour": {},
        "checks": 0,
        "errors": 0,
        "found_total": 0,
        "last_found_at": None,
    }


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
        "stats": empty_stats(),
        "telegram_topic_id": None,
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
            record["stats"] = empty_stats()
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


def set_telegram_topic_id(url_id: str, topic_id: int | None) -> dict[str, Any] | None:
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return None
        record["telegram_topic_id"] = topic_id
        return dict(record)


def get_stats(record: dict[str, Any]) -> dict[str, Any]:
    """Stats of a record, tolerating entries written before stats existed."""
    stats = record.get("stats")
    if not isinstance(stats, dict):
        return empty_stats()
    return {**empty_stats(), **stats}


def _prune(buckets: dict[str, Any], limit: int) -> dict[str, Any]:
    if len(buckets) <= limit:
        return buckets
    # Hour keys sort chronologically as plain strings.
    return {key: buckets[key] for key in sorted(buckets)[-limit:]}


def record_poll(
    url_id: str,
    *,
    error: str | None = None,
    found_count: int = 0,
    listed_timestamps: Iterable[int] = (),
) -> None:
    """Persist the outcome of a single poll: timestamp, error and statistics."""
    retention = get_settings().stats_retention_hours
    now = datetime.now(tz=timezone.utc)

    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return
        record["last_checked_at"] = utc_now()
        record["last_error"] = error

        stats = get_stats(record)
        stats["checks"] += 1
        if error:
            stats["errors"] += 1

        if found_count:
            bucket = hour_key(now)
            stats["found_by_hour"][bucket] = stats["found_by_hour"].get(bucket, 0) + found_count
            stats["found_by_hour"] = _prune(stats["found_by_hour"], retention)
            stats["found_total"] += found_count
            stats["last_found_at"] = utc_now()

        for timestamp in listed_timestamps:
            try:
                listed_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            except (OverflowError, OSError, ValueError, TypeError):
                continue
            bucket = hour_key(listed_at)
            stats["listed_by_hour"][bucket] = stats["listed_by_hour"].get(bucket, 0) + 1
        stats["listed_by_hour"] = _prune(stats["listed_by_hour"], retention)

        record["stats"] = stats


def reset_stats(url_id: str) -> bool:
    with get_store().transaction() as data:
        record = _find(data, url_id)
        if record is None:
            return False
        record["stats"] = empty_stats()
        return True


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
