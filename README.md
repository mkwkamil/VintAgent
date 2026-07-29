# VintAgent

Lightweight Vinted URL manager and scraper for a single small VM (e.g. Google Cloud Free Tier, 1 GB RAM).

One Docker container serves both the React dashboard and the FastAPI backend. Tracked searches run in background threads; new listings go to a Telegram forum group (one topic per tracker). Scraped items are **never** shown in the UI.

## Features

- Admin login (JWT)
- Up to 10 concurrent trackers (configurable)
- Vinted session via HTTP token refresh (no Chromium required on the server)
- Phone rescue: Telegram alert + one-time link + bookmarklet when the session dies
- Per-tracker Telegram topics
- Stats: finds over time, posting hour-of-day histogram
- Single JSON file storage (`data.json`), no database

## Quick start

```bash
cp backend/.env.example backend/.env
# set ADMIN_PASSWORD, JWT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PUBLIC_BASE_URL

mkdir -p backend/data
docker compose up --build -d
```

Open `http://localhost:8000`.

### Required `.env`

| Variable | Notes |
|---|---|
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Dashboard login — change defaults |
| `JWT_SECRET` | Long random string |
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `TELEGRAM_CHAT_ID` | Forum **group** id (`-100…`), bot must be admin with Topics rights |
| `PUBLIC_BASE_URL` | Public URL of this instance (e.g. `http://IP:8000`) — needed for the rescue button |

Optional knobs: `MAX_THREADS`, poll intervals, rescue TTL, paths — see `backend/.env.example`.

## Session & phone rescue

Day-to-day the server renews tokens with `POST /web/api/auth/refresh` (no browser).
The keeper checks every minute and forces a refresh about every 45 minutes so a
2-hour access token never silently dies.

**If you mostly only have a phone:** you cannot pull cookies from the Vinted app.
The reliable lightweight setup is:

1. Seed `session.json` once (from a laptop / home browser → **Wklej**)
2. Let HTTP keep-alive run on the VM
3. **Required on GCP:** set `VINTED_PROXY` to a residential proxy — datacenter IP gets
   HTTP 403 even with valid JWTs because `datadome` / `cf_clearance` are IP-bound.
   Cookies copied from your home PC to the VM **will not** fix 403 on GCP alone.
4. Rescue alert remains a last resort (bookmarklet / paste in mobile browser)

When refresh still fails, VintAgent sends Telegram **Odnów sesję**. Chromium is
off by default (`BROWSER_BOOTSTRAP_ENABLED=false`).

## Update

```bash
git pull
docker compose up --build -d
```

`backend/data/` is mounted — trackers and session survive rebuilds.

## API (admin JWT unless noted)

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Public health check |
| POST | `/api/auth/login` | Login → JWT |
| GET | `/api/auth/me` | Current user |
| GET | `/api/stats` | Active threads / Telegram status |
| GET | `/api/session` | Vinted session status |
| POST | `/api/session/refresh` | Force Chromium cookie bootstrap |
| POST | `/api/session/import` | Paste Cookie header from a browser |
| GET | `/api/session/rescue/{token}` | Public rescue link status |
| POST | `/api/session/rescue/{token}` | Public cookie import (one-time) |
| POST | `/api/session/rescue/{token}/form` | Bookmarklet form POST |
| POST | `/api/session/rescue/test` | Force rescue Telegram alert |
| POST | `/api/telegram/test` | Send a test message |
| GET/POST | `/api/urls` | List / create trackers |
| GET/PATCH/DELETE | `/api/urls/{id}` | Detail / update / delete |
| GET | `/api/urls/{id}/stats` | Chart series |
| POST | `/api/urls/{id}/stats/reset` | Clear stats |
| POST | `/api/urls/{id}/telegram-topic` | Create missing forum topic |
| POST | `/api/urls/{id}/start` | Start scraper thread |
| POST | `/api/urls/{id}/stop` | Stop scraper thread |

First poll after start is a **seed** (no Telegram spam). Only later new items notify.

## Local development

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # optional, for cookie bootstrap
uvicorn app.main:app --reload --port 8000

# Frontend (proxies /api → :8000)
cd frontend
npm install
npm run dev
```

Offline session tests:

```bash
cd backend && python scripts/session_test.py
```

## Project layout

```
VintAgent/
├── Dockerfile
├── docker-compose.yml
├── backend/
│   ├── app/           # FastAPI, scraper, session, Telegram
│   ├── data/          # runtime volume (gitignored)
│   ├── scripts/       # smoke + session tests
│   └── .env.example
└── frontend/          # Vite + React + TypeScript + Tailwind
```

## License

Private / personal use unless stated otherwise.
