#!/bin/sh
set -eu

PROFILE_DIR="${BROWSER_PROFILE_DIR:-/app/data/chrome_cdp}"
CDP_PORT="${CHROME_CDP_PORT:-9222}"
mkdir -p "$PROFILE_DIR" /app/data

CHROME_BIN=""
for candidate in /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome-stable; do
  if [ -x "$candidate" ]; then
    CHROME_BIN="$candidate"
    break
  fi
done

start_xvfb() {
  if ! pgrep -x Xvfb >/dev/null 2>&1; then
    echo "Starting Xvfb"
    Xvfb :99 -screen 0 1365x900x24 -ac +extension GLX +render -noreset >/tmp/xvfb.log 2>&1 &
    sleep 0.5
  fi
  export DISPLAY=:99
}

start_chromium() {
  if [ -z "$CHROME_BIN" ]; then
    echo "ERROR: Chromium not found in image" >&2
    return 1
  fi

  # Zabij stare procesy tego profilu (crash / zombie CDP)
  pkill -f "--user-data-dir=${PROFILE_DIR}" >/dev/null 2>&1 || true
  sleep 0.5

  # Po recreate kontenera Chromium zostawia SingletonLock z innym hostname — bez tego CDP nigdy nie wstanie.
  rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonCookie" "$PROFILE_DIR/SingletonSocket" \
        "$PROFILE_DIR/Default/SingletonLock" "$PROFILE_DIR/Default/SingletonCookie" "$PROFILE_DIR/Default/SingletonSocket" \
        2>/dev/null || true

  echo "Starting Chromium CDP on :$CDP_PORT"
  "$CHROME_BIN" \
    --remote-debugging-port="$CDP_PORT" \
    --remote-allow-origins="*" \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --disable-software-rasterizer \
    --disable-extensions \
    --disable-background-networking \
    --disable-background-timer-throttling \
    --disable-renderer-backgrounding \
    --disable-features=TranslateUI \
    --mute-audio \
    --renderer-process-limit=2 \
    about:blank >/tmp/chromium.log 2>&1 &

  i=0
  while [ "$i" -lt 40 ]; do
    if wget -q -O /dev/null "http://127.0.0.1:${CDP_PORT}/json/version" 2>/dev/null; then
      echo "Chromium CDP ready"
      return 0
    fi
    i=$((i + 1))
    sleep 0.5
  done
  echo "WARNING: Chromium CDP not ready — /tmp/chromium.log:" >&2
  tail -n 50 /tmp/chromium.log 2>/dev/null || true
  return 1
}

cdp_watchdog() {
  while true; do
    sleep 20
    if ! wget -q -O /dev/null "http://127.0.0.1:${CDP_PORT}/json/version" 2>/dev/null; then
      echo "Chromium CDP down — restarting"
      start_xvfb || true
      start_chromium || true
    fi
  done
}

if [ "${BROWSER_BOOTSTRAP_ENABLED:-true}" = "true" ]; then
  start_xvfb
  start_chromium || true
  cdp_watchdog &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
