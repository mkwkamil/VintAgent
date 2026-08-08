# VintAgent

Vinted search tracker with a React dashboard and FastAPI backend.
New listings go to **Telegram** (forum topics) — scraped items are not shown in the UI.

## How the session works

1. Real Chrome/Chromium with remote debugging (CDP) and a dedicated profile (`data/chrome_cdp/`)
2. Cookies are read via `Network.getAllCookies`
3. Scrapers call the Vinted catalog with `curl_cffi` using that cookie jar
4. HTTP JWT refresh keeps the session alive; on HTTP 403 the backend re-syncs from CDP (and restarts Chromium if CDP is down)

**Local (Mac/desktop):** a Chrome window opens — sign in to vinted.pl; the backend detects `access_token_web` automatically.

**Docker:** Chromium + Xvfb run inside the container. If Cloudflare blocks anonymous token minting, use **Emergency Cookie import** in the dashboard (or seed a working CDP profile).

## Docker (recommended)

```bash
cp backend/.env.example backend/.env
# set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_*, JWT_SECRET

docker compose up --build -d
# open http://localhost:8000
```

Needs about **1 GB RAM** on the host (`mem_limit: 900m` plus OS overhead). Data persists in `backend/data/`.

## Local development

Requires **Google Chrome** installed.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DATA_FILE=data/data.json
# SESSION_FILE=data/session.json

uvicorn app.main:app --reload --port 8000
```

Frontend (optional for UI changes):

```bash
cd frontend
npm ci
npm run dev
# or: npm run build  → copy dist into backend/static if serving from uvicorn only
```

## Config notes

- Keep `DATA_FILE` and `SESSION_FILE` as **separate** paths (never the same file).
- Docker Compose overrides paths to `/app/data/*` inside the container.
- Do not commit `.env`, `session.json`, or the Chrome profile directories.
