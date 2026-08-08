"""Sesja Vinted przez prawdziwy Chrome/Chromium + CDP (jak CookieScraper).

Lokalnie: Google Chrome. W Dockerze: Chromium + Xvfb (entrypoint).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ACCESS_TOKEN_COOKIE = "access_token_web"

CHROME_PATHS = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
)


def in_docker() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("CHROME_DOCKER") == "1"


def _cdp_ws_send(ws: Any, method: str, params: dict | None = None, *, msg_id: int = 1) -> dict:
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
    while True:
        data = json.loads(ws.recv())
        if data.get("id") == msg_id:
            if error := data.get("error"):
                raise RuntimeError(f"CDP {method}: {error}")
            return data.get("result") or {}


def _browser_ws_url(cdp_url: str) -> str:
    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=5) as resp:
        return json.loads(resp.read())["webSocketDebuggerUrl"]


def _list_cdp_targets(cdp_url: str) -> list[dict]:
    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/list", timeout=5) as resp:
        targets = json.loads(resp.read())
    return targets if isinstance(targets, list) else []


def _pick_page_target(cdp_url: str) -> dict:
    targets = _list_cdp_targets(cdp_url)
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        raise RuntimeError("Brak otwartej karty w Chrome — CDP nie gotowe.")
    for page in pages:
        if "vinted" in (page.get("url") or "").lower():
            return page
    return pages[0]


def read_cookies_cdp(cdp_url: str) -> dict[str, str]:
    import websocket

    page = _pick_page_target(cdp_url)
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=15)
    try:
        try:
            result = _cdp_ws_send(ws, "Network.getAllCookies", msg_id=1)
        except RuntimeError:
            _cdp_ws_send(ws, "Network.enable", msg_id=2)
            result = _cdp_ws_send(ws, "Network.getAllCookies", msg_id=3)
    finally:
        ws.close()
    return {
        c["name"]: c["value"]
        for c in result.get("cookies", [])
        if c.get("name") and c.get("value")
    }


def read_user_agent_cdp(cdp_url: str) -> str:
    import websocket

    try:
        page = _pick_page_target(cdp_url)
    except RuntimeError:
        return ""
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10)
    try:
        result = _cdp_ws_send(
            ws,
            "Runtime.evaluate",
            {"expression": "navigator.userAgent", "returnByValue": True},
            msg_id=1,
        )
        return str(result.get("result", {}).get("value") or "")
    finally:
        ws.close()


def open_url_cdp(cdp_url: str, url: str) -> None:
    import websocket

    ws = websocket.create_connection(_browser_ws_url(cdp_url), timeout=10)
    try:
        _cdp_ws_send(ws, "Target.createTarget", {"url": url}, msg_id=1)
    finally:
        ws.close()


def navigate_active_page(cdp_url: str, url: str) -> None:
    """Nawigacja w istniejącej karcie (lepsze w Dockerze niż nowa karta)."""
    import websocket

    page = _pick_page_target(cdp_url)
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
    try:
        _cdp_ws_send(ws, "Page.enable", msg_id=1)
        _cdp_ws_send(ws, "Page.navigate", {"url": url}, msg_id=2)
    finally:
        ws.close()


def cdp_http_ok(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=2) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def cdp_ws_ok(cdp_url: str) -> bool:
    if not cdp_http_ok(cdp_url):
        return False
    try:
        import websocket

        ws = websocket.create_connection(_browser_ws_url(cdp_url), timeout=5)
        ws.close()
        return True
    except Exception:
        return False


def find_chrome() -> str:
    for path in CHROME_PATHS:
        if Path(path).is_file():
            return path
    raise RuntimeError(
        "Nie znaleziono Chrome/Chromium. W Dockerze użyj obrazu z Chromium; lokalnie zainstaluj Google Chrome."
    )


def kill_cdp_chrome(profile_dir: Path, port: int) -> None:
    try:
        subprocess.run(
            ["pkill", "-f", f"--user-data-dir={profile_dir}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not cdp_http_ok(f"http://127.0.0.1:{port}"):
            break
        time.sleep(0.3)
    # Stary SingletonLock z poprzedniego kontenera blokuje start Chromium na zawsze.
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except Exception:
            pass


def start_cdp_chrome(
    cdp_url: str,
    *,
    profile_dir: Path,
    chrome_path: str = "",
    start_url: str | None = None,
) -> None:
    parsed = urlparse(cdp_url)
    port = parsed.port or 9222
    profile_dir.mkdir(parents=True, exist_ok=True)

    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile_dir / name).unlink(missing_ok=True)
        except Exception:
            pass

    chrome = chrome_path.strip() or find_chrome()
    logger.info("Uruchamiam Chrome CDP (port %s, profile %s)", port, profile_dir)

    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={str(profile_dir)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if in_docker():
        cmd.extend(
            [
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-background-networking",
                "--mute-audio",
                "--renderer-process-limit=2",
            ]
        )
    cmd.append(start_url or "about:blank")

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if cdp_ws_ok(cdp_url):
            time.sleep(1.0)
            logger.info("Chrome CDP gotowy")
            return
        time.sleep(0.5)

    raise RuntimeError("Chrome/Chromium nie wystartował (CDP).")


def ensure_cdp_chrome(
    cdp_url: str,
    *,
    profile_dir: Path,
    chrome_path: str = "",
    start_url: str | None = None,
) -> None:
    if cdp_ws_ok(cdp_url):
        if start_url:
            try:
                navigate_active_page(cdp_url, start_url)
            except Exception:
                try:
                    open_url_cdp(cdp_url, start_url)
                except Exception:
                    logger.debug("Nie udało się otworzyć URL w CDP", exc_info=True)
        return

    parsed = urlparse(cdp_url)
    port = parsed.port or 9222

    # W Dockerze Chromium często pada po godzinach — restart zamiast martwego czekania.
    logger.warning("CDP nie odpowiada — restartuję Chromium (docker=%s)", in_docker())
    kill_cdp_chrome(profile_dir, port)
    start_cdp_chrome(
        cdp_url,
        profile_dir=profile_dir,
        chrome_path=chrome_path or ("/usr/bin/chromium" if in_docker() else ""),
        start_url=start_url,
    )


def wait_for_access_token(
    cdp_url: str,
    *,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 2.0,
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    last_log = 0.0
    while time.monotonic() < deadline:
        try:
            cookies = read_cookies_cdp(cdp_url)
        except Exception as exc:
            logger.debug("CDP cookie read: %s", exc)
            cookies = {}
        if ACCESS_TOKEN_COOKIE in cookies:
            return cookies
        now = time.monotonic()
        if now - last_log >= 15:
            logger.info("Czekam na access_token_web z CDP… %.0fs pozostało", deadline - now)
            last_log = now
        time.sleep(poll_seconds)
    raise RuntimeError("Timeout — brak access_token_web z Chrome CDP")


def sync_cookies_from_cdp(
    *,
    cdp_url: str,
    base_url: str,
    profile_dir: Path,
    chrome_path: str = "",
    force_login: bool = False,
    login_timeout_seconds: float = 90.0,
) -> tuple[dict[str, str], str]:
    """Czyta cookies z Chrome CDP. W Dockerze bez interaktywnego logowania w oknie."""
    base = base_url.rstrip("/")
    home = f"{base}/"
    catalog = f"{base}/catalog"
    wait_s = min(login_timeout_seconds, 90.0 if in_docker() else login_timeout_seconds)

    ensure_cdp_chrome(
        cdp_url,
        profile_dir=profile_dir,
        chrome_path=chrome_path,
        start_url=home,
    )

    time.sleep(2.0)
    cookies: dict[str, str] = {}
    try:
        cookies = read_cookies_cdp(cdp_url)
    except Exception:
        logger.debug("Pierwszy odczyt cookies nieudany", exc_info=True)

    if ACCESS_TOKEN_COOKIE not in cookies:
        try:
            navigate_active_page(cdp_url, catalog)
        except Exception:
            open_url_cdp(cdp_url, catalog)
        time.sleep(2.0)
        try:
            cookies = wait_for_access_token(cdp_url, timeout_seconds=wait_s)
        except RuntimeError:
            try:
                cookies = read_cookies_cdp(cdp_url)
            except Exception:
                pass

    if ACCESS_TOKEN_COOKIE not in cookies:
        if in_docker():
            raise RuntimeError(
                "Chromium w Dockerze nie dostał access_token_web (Cloudflare). "
                "Wklej Cookie w panelu (awaryjny import) albo skopiuj profil z CookieScraper "
                "do backend/data/chrome_cdp/"
            )
        if force_login:
            open_url_cdp(cdp_url, f"{base}/member/signup/select_type")
            logger.warning("Zaloguj się w oknie Chrome — czekam…")
            cookies = wait_for_access_token(cdp_url, timeout_seconds=login_timeout_seconds)
        else:
            raise RuntimeError(
                "Brak access_token_web — zaloguj się w Chrome albo użyj Odśwież sesję"
            )

    if ACCESS_TOKEN_COOKIE not in cookies:
        raise RuntimeError("Brak access_token_web po synchronizacji CDP")

    user_agent = read_user_agent_cdp(cdp_url)
    logger.info("CDP: pobrano %d cookies", len(cookies))
    return cookies, user_agent
