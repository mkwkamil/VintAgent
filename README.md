# VintAgent

Lightweight Vinted URL manager and scraper for a single small VM (e.g. Google Cloud Free Tier, 1 GB RAM).

One Docker container serves both the React dashboard and the FastAPI backend. Tracked searches run in background threads; new listings go to a Telegram forum group (one topic per tracker). Scraped items are **never** shown in the UI.

## Features

- Admin login (JWT)
- Up to 10 concurrent trackers (configurable)
- Automatic Vinted session: HTTP token refresh, Chromium only when Cloudflare blocks
- Per-tracker Telegram topics
- Stats: finds over time, posting hour-of-day histogram
- Single JSON file storage (`data.json`), no database

## Quick start

```bash
cp backend/.env.example backend/.env
# set ADMIN_PASSWORD, JWT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

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

Optional knobs: `MAX_THREADS`, poll intervals, browser bootstrap, paths — see `backend/.env.example`.

## Architecture

```
Browser ──► FastAPI (:8000)
              ├── /api/*          JSON API + JWT
              ├── /               React static build
              ├── ThreadManager   1 thread per running tracker
              ├── SessionKeeper   keeps Vinted cookies warm
              └── data/           data.json + session.json (volume)
```

Scraping uses `curl_cffi` (Chrome TLS impersonation). Headless Chromium (Playwright) starts only to obtain cookies when a plain request cannot.

**GCP / Cloudflare tip:** Datacenter IPs often fail the JS challenge. Bootstrap once on a home machine, then copy `backend/data/session.json` to the server (or use **Wklej** in the nav). HTTP refresh keeps the session alive afterwards.

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
