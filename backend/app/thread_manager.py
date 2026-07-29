"""Background scraping threads, one per tracked URL.

Fault tolerance has two layers: each poll iteration catches its own exceptions and
backs off, and the thread body itself is wrapped so that even an unexpected crash
only pauses the worker instead of killing it. Either way the FastAPI process is
never affected.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from typing import Any

from . import storage, telegram
from .config import Settings, get_settings
from .scraper import VintedBlocked, VintedScraper

logger = logging.getLogger(__name__)

CRASH_RESTART_SECONDS = 5.0

# Raw exception text (curl error codes, stack-ish detail) is useless on a card,
# so the common failures get a plain-Polish equivalent.
ERROR_MESSAGES = {
    "ConnectionError": "Brak połączenia z Vinted, ponawiam",
    "Timeout": "Vinted nie odpowiedział na czas, ponawiam",
    "ConnectTimeout": "Vinted nie odpowiedział na czas, ponawiam",
    "JSONDecodeError": "Vinted zwrócił nieoczekiwaną odpowiedź, ponawiam",
}


def describe_error(exc: Exception) -> str:
    return ERROR_MESSAGES.get(type(exc).__name__, f"{type(exc).__name__}: {exc}"[:200])


class MaxThreadsReached(RuntimeError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"Osiągnięto limit {limit} aktywnych wątków")
        self.limit = limit


@dataclass(slots=True)
class _Worker:
    thread: threading.Thread
    stop_event: threading.Event


class ThreadManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._workers: dict[str, _Worker] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle

    def start(self, url_id: str) -> None:
        with self._lock:
            self._prune_locked()
            if url_id in self._workers:
                return
            if len(self._workers) >= self._settings.max_threads:
                raise MaxThreadsReached(self._settings.max_threads)

            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._thread_main,
                args=(url_id, stop_event),
                name=f"scraper-{url_id[:8]}",
                daemon=True,
            )
            self._workers[url_id] = _Worker(thread=thread, stop_event=stop_event)
            thread.start()
        logger.info("Started scraper thread for %s", url_id)

    def stop(self, url_id: str, timeout: float = 5.0) -> bool:
        with self._lock:
            worker = self._workers.get(url_id)
        if worker is None:
            return False

        worker.stop_event.set()
        worker.thread.join(timeout=timeout)
        with self._lock:
            if self._workers.get(url_id) is worker and not worker.thread.is_alive():
                del self._workers[url_id]
        logger.info("Stopped scraper thread for %s", url_id)
        return True

    def restart(self, url_id: str) -> None:
        self.stop(url_id)
        self.start(url_id)

    def stop_all(self, timeout: float = 5.0) -> None:
        with self._lock:
            workers = dict(self._workers)
        for worker in workers.values():
            worker.stop_event.set()
        for worker in workers.values():
            worker.thread.join(timeout=timeout)
        with self._lock:
            self._workers.clear()

    # ------------------------------------------------------------------ queries

    def is_running(self, url_id: str) -> bool:
        with self._lock:
            worker = self._workers.get(url_id)
            return worker is not None and worker.thread.is_alive()

    def active_count(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._workers)

    @property
    def max_threads(self) -> int:
        return self._settings.max_threads

    # ------------------------------------------------------------------ internals

    def _prune_locked(self) -> None:
        for url_id in [uid for uid, w in self._workers.items() if not w.thread.is_alive()]:
            del self._workers[url_id]

    def _forget(self, url_id: str) -> None:
        with self._lock:
            worker = self._workers.get(url_id)
            if worker is not None and worker.thread is threading.current_thread():
                del self._workers[url_id]

    def _thread_main(self, url_id: str, stop_event: threading.Event) -> None:
        scraper = VintedScraper(self._settings)
        try:
            while not stop_event.is_set():
                try:
                    self._poll_loop(url_id, scraper, stop_event)
                    return
                except BaseException:
                    logger.exception("Scraper thread %s crashed, restarting in %ss", url_id, CRASH_RESTART_SECONDS)
                    stop_event.wait(CRASH_RESTART_SECONDS)
        finally:
            scraper.close()
            self._forget(url_id)

    def _poll_loop(self, url_id: str, scraper: VintedScraper, stop_event: threading.Event) -> None:
        settings = self._settings
        while not stop_event.is_set():
            delay = random.uniform(settings.poll_min_seconds, settings.poll_max_seconds)
            try:
                record = storage.get_url(url_id)
                if record is None:
                    logger.info("URL %s was deleted, ending thread", url_id)
                    return
                self._poll_once(record, scraper)
            except VintedBlocked as exc:
                logger.warning("%s: %s", url_id, exc)
                storage.record_poll(url_id, error=str(exc))
                try:
                    scraper.refresh_session()
                except Exception:
                    logger.exception("Session refresh failed for %s", url_id)
                delay = random.uniform(
                    settings.blocked_backoff_min_seconds,
                    settings.blocked_backoff_max_seconds,
                )
            except Exception as exc:
                logger.exception("Polling failed for %s", url_id)
                storage.record_poll(url_id, error=describe_error(exc))
                delay = settings.error_backoff_seconds

            stop_event.wait(delay)

    def _poll_once(self, record: dict[str, Any], scraper: VintedScraper) -> None:
        url_id = record["id"]
        items = scraper.fetch_items(record["url"])
        item_ids = [item.id for item in items]

        if not record.get("seeded"):
            storage.record_seen(url_id, item_ids)
            storage.record_poll(url_id)
            logger.info("Seeded '%s' with %d item(s), no notifications sent", record["name"], len(items))
            return

        known = set(record.get("seen_ids") or [])
        new_items = [item for item in items if item.id not in known]
        # Vinted returns newest first; notify in listing order (oldest new item first).
        topic_id = record.get("telegram_topic_id")
        try:
            message_thread_id = int(topic_id) if topic_id is not None else None
        except (TypeError, ValueError):
            message_thread_id = None
        for item in reversed(new_items):
            telegram.send_item(
                item,
                record["name"],
                self._settings,
                source_url=record["url"],
                message_thread_id=message_thread_id,
            )

        storage.record_seen(url_id, item_ids)
        storage.record_poll(
            url_id,
            found_count=len(new_items),
            listed_timestamps=[item.listed_ts for item in new_items if item.listed_ts],
        )
        if new_items:
            logger.info("'%s': found %d new item(s)", record["name"], len(new_items))


_manager: ThreadManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> ThreadManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ThreadManager()
        return _manager
