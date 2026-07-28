# VintAgent

Lekki manager i scraper URL-i Vinted, zaprojektowany pod Google Cloud Free Tier (1 GB RAM, 30 GB dysku).
Frontend (Vite + React + TS) i backend (FastAPI) działają w **jednym kontenerze** — FastAPI serwuje API pod
`/api` oraz zbudowane pliki statyczne Reacta pod `/`.

## Architektura

- **Jeden kontener**, multi-stage build: `node:20-alpine` buduje frontend, `python:3.11-slim` uruchamia backend.
- **Baza danych:** plik `backend/data/data.json` (bez SQL), zapisy atomowe pod blokadą wątkową.
- **Scraper:** wątki `threading.Thread` (maks. 6 równocześnie), `curl_cffi` z impersonacją Chrome,
  losowy interwał 10–15 s, odporność na błędy 403/429.
- **Powiadomienia:** Telegram Bot API (token i chat ID w `.env`).
- **Dashboard:** wyłącznie zarządzanie URL-ami (start/stop/edycja/usuwanie). Zescrapowane ogłoszenia
  **nie są** wyświetlane w UI — trafiają tylko na Telegram.

## Struktura

```
VintAgent/
├── Dockerfile              # multi-stage: node builder -> python runtime
├── docker-compose.yml      # pojedyncza usługa + wolumen na data.json
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── data/               # data.json (wolumen, poza obrazem)
│   └── app/
│       ├── main.py         # FastAPI: /api + StaticFiles na /
│       └── api/
└── frontend/               # Vite + React + TypeScript + Tailwind 4
    └── src/
        ├── api/client.ts   # fetch + JWT
        ├── auth/           # AuthContext
        ├── components/     # TopNav, UrlCard, UrlFormModal, StatusBadge
        └── pages/          # Login, Dashboard
```

## Uruchomienie (Docker)

```bash
cp backend/.env.example backend/.env   # uzupełnij dane logowania i Telegram
docker compose up --build
```

Aplikacja: http://localhost:8000 &nbsp;·&nbsp; health check: http://localhost:8000/api/health

## API

| Metoda | Endpoint | Opis |
|---|---|---|
| GET | `/api/health` | Health check (publiczny) |
| POST | `/api/auth/login` | Logowanie admina, zwraca token JWT |
| GET | `/api/auth/me` | Weryfikacja tokenu |
| GET | `/api/stats` | Liczba aktywnych wątków, limit, status Telegrama |
| POST | `/api/telegram/test` | Wysyła wiadomość testową na Telegram |
| GET | `/api/urls` | Lista śledzonych URL-i |
| POST | `/api/urls` | Dodanie URL-a (start ręczny) |
| PATCH | `/api/urls/{id}` | Zmiana nazwy lub URL-a |
| DELETE | `/api/urls/{id}` | Usunięcie URL-a i zatrzymanie wątku |
| POST | `/api/urls/{id}/start` | Start wątku (409 przy limicie wątków) |
| POST | `/api/urls/{id}/stop` | Zatrzymanie wątku |

Wszystkie endpointy poza `/api/health` i `/api/auth/login` wymagają nagłówka `Authorization: Bearer <token>`.

Pierwsze odpytanie po starcie URL-a to **seed**: zapisuje aktualne ogłoszenia jako znane i nie wysyła
powiadomień. Dopiero kolejne, nowe ogłoszenia trafiają na Telegram.

## Cloudflare i `VINTED_COOKIE`

Vinted stoi za Cloudflare, który dla części adresów IP odpowiada na anonimowe zapytania
**wyzwaniem JavaScript**. Żadne nagłówki ani profil TLS tego nie obejdą (dlatego scraper zgłasza wtedy
`Cloudflare wymaga weryfikacji JS`). Rozwiązanie: pożycz sesję z własnej przeglądarki.

1. Zaloguj się na Vinted w przeglądarce.
2. DevTools → Network → dowolne zapytanie do `vinted.pl` → Request Headers → skopiuj całą wartość `Cookie`.
3. Wklej ją do `backend/.env` jako `VINTED_COOKIE=...` i zrestartuj kontener.

Kluczowe są `access_token_web`, `refresh_token_web`, `anon_id` i `cf_clearance`. Jeśli Cloudflare
Twojego IP nie wyzwala (często tak jest na VM-kach w GCP), scraper działa bez tej zmiennej.

### Automatyczne odnawianie sesji

`access_token_web` żyje tylko 2 h, ale obok niego jest `refresh_token_web` ważny 7 dni. VintAgent na
10 minut przed wygaśnięciem (`SESSION_REFRESH_MARGIN_SECONDS`) woła `POST /web/api/auth/refresh`,
dostaje nową parę tokenów i zapisuje ją do `backend/data/session.json` (prawa `0600`). Ponieważ przy
każdym odnowieniu refresh token dostaje **nowe 7 dni**, jedno wklejenie cookies wystarcza tak długo,
jak długo aplikacja działa.

Ponieważ Vinted rotuje oba tokeny naraz, odnowieniem zajmuje się tylko jeden wątek — pozostałe czekają
i podchwytują nowe cookies ze wspólnego magazynu (`app/session_store.py`). Przy starcie wygrywa ten
zestaw cookies, którego refresh token jest ważny dłużej, więc świeżo wklejone `VINTED_COOKIE`
nadpisuje stary `session.json`, a po restarcie kontenera używany jest zapisany, odnowiony zestaw.

Testy tej warstwy (offline, bez ruchu do Vinted):

```bash
cd backend && python scripts/session_test.py
```

Uwaga przy wdrożeniu: `cf_clearance` i `datadome` są związane z adresem IP i User-Agentem, dla których
powstały. Cookies z przeglądarki na laptopie mogą nie zadziałać na VM-ce z innym IP.

Test dymny API (wymaga uruchomionego backendu):

```bash
cd backend
DATA_FILE=/tmp/vintagent_test.json ADMIN_PASSWORD=test123 python scripts/smoke_test.py http://127.0.0.1:8000
```

## Development lokalny

Backend (z auto-reloadem, bez plików statycznych):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Vite dev server proxuje `/api` na `localhost:8000`):

```bash
cd frontend
npm install
npm run dev
```
