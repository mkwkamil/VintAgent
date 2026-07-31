"""Compatibility shim — session lifecycle lives in session_manager."""

from __future__ import annotations

from .session_manager import SessionManager, get_session_manager


class SessionKeeper:
    """Deprecated name; browser manager replaces the old HTTP-only keeper."""

    def start(self) -> None:
        get_session_manager().start()

    def stop(self, timeout: float = 15.0) -> None:
        get_session_manager().stop(timeout=timeout)


def get_keeper() -> SessionKeeper:
    return SessionKeeper()
