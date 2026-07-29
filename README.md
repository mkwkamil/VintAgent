# VintAgent

Lekki manager i scraper URL-i Vinted, zaprojektowany pod Google Cloud Free Tier (1 GB RAM, 30 GB dysku).
Frontend (Vite + React + TS) i backend (FastAPI) działają w **jednym kontenerze** — FastAPI serwuje API pod
`/api` oraz zbudowane pliki statyczne Reacta pod `/`.

## Architektura

- **Jeden kontener**, multi-stage build: `node:24-alpine` buduje frontend, `python:3.11-slim` uruchamia backend.
- **Baza danych:** plik `backend/data/data.json` (bez SQL), zapisy atomowe pod blokadą wątkową.
- **Scraper:** wątki `threading.Thread` (maks. 10 równocześnie), `curl_cffi` z impersonacją Chrome,
  losowy interwał 10–15 s, odporność na błędy 403/429.
- **Sesja Vinted:** w pełni automatyczna — odświeżanie tokenu po HTTP, a headless Chromium tylko
  wtedy, gdy trzeba przejść wyzwanie Cloudflare.
- **Powiadomienia:** Telegram Bot API — każdy tracker ma własny **topic** w grupie
  (tworzony automatycznie przy dodaniu URL-a). Token i ID grupy w `.env`.
- **Dashboard:** zarządzanie URL-ami (start/stop/edycja/usuwanie) plus statystyki każdego linku.
  Zescrapowane ogłoszenia **nie są** wyświetlane w UI — trafiają tylko na Telegram.

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
│       ├── scraper.py      # curl_cffi + translacja URL-i katalogu na API
│       ├── session_store.py    # wspólne cookies + zapis do session.json
│       ├── browser_session.py  # headless Chromium: bootstrap cookies
│       ├── session_keeper.py   # watchdog odnawiający sesję w tle
│       ├── analytics.py    # agregacja kubełków godzinowych na wykresy
│       └── api/
└── frontend/               # Vite + React + TypeScript + Tailwind 4
    └── src/
        ├── api/client.ts   # fetch + JWT
        ├── auth/           # AuthContext
        ├── components/     # TopNav, UrlCard, BarChart, UrlFormModal, StatusBadge
        ├── lib/            # formatowanie dat, router na hashu
        └── pages/          # Login, Dashboard, UrlDetail
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
| GET | `/api/session` | Stan sesji Vinted (ważność tokenu, dostępność Chromium) |
| POST | `/api/session/refresh` | Wymusza odnowienie cookies przez headless Chromium |
| POST | `/api/telegram/test` | Wysyła wiadomość testową na Telegram |
| GET | `/api/urls` | Lista śledzonych URL-i wraz z podsumowaniem statystyk |
| POST | `/api/urls` | Dodanie URL-a (start ręczny) |
| GET | `/api/urls/{id}` | Szczegóły pojedynczego URL-a |
| GET | `/api/urls/{id}/stats` | Serie do wykresów (`hours`, `tz_offset_minutes`) |
| POST | `/api/urls/{id}/stats/reset` | Czyści historię statystyk linku |
| PATCH | `/api/urls/{id}` | Zmiana nazwy lub URL-a |
| DELETE | `/api/urls/{id}` | Usunięcie URL-a i zatrzymanie wątku |
| POST | `/api/urls/{id}/telegram-topic` | Tworzy topic w grupie Telegram dla istniejącego trackera |
| POST | `/api/urls/{id}/start` | Start wątku (409 przy limicie wątków) |
| POST | `/api/urls/{id}/stop` | Zatrzymanie wątku |

Wszystkie endpointy poza `/api/health` i `/api/auth/login` wymagają nagłówka `Authorization: Bearer <token>`.

Pierwsze odpytanie po starcie URL-a to **seed**: zapisuje aktualne ogłoszenia jako znane i nie wysyła
powiadomień. Dopiero kolejne, nowe ogłoszenia trafiają na Telegram.

## Sesja Vinted (w pełni automatyczna)

Vinted stoi za Cloudflare, który dla części adresów IP odpowiada na anonimowe zapytania
**wyzwaniem JavaScript**. Żadne nagłówki ani profil TLS tego nie obejdą — potrzebna jest przeglądarka,
która wykona ten skrypt. VintAgent robi to sam, w trzech poziomach:

1. **Zwykłe zapytanie HTTP** (`curl_cffi`) — tak działa każde odpytanie katalogu.
2. **Odświeżenie tokenu** — na 10 minut przed wygaśnięciem `access_token_web` leci
   `POST /web/api/auth/refresh`, który zwraca nową parę tokenów (kilka kB ruchu).
3. **Headless Chromium** — tylko gdy nie ma z czego odświeżać albo Cloudflare zablokował zapytanie.
   Przeglądarka wchodzi na stronę główną, przechodzi wyzwanie, oddaje cookies i natychmiast się zamyka.

Cookies lądują w `backend/data/session.json` (prawa `0600`) i przeżywają restart kontenera.
Nie ma czego wklejać do `.env` na co dzień.

### Gdy Chromium na serwerze nie dostaje tokenu (GCP / Cloudflare)

IP datacenter często nie przechodzi wyzwania JS, nawet z prawdziwą przeglądarką. Lokalnie (IP
domowe) działa, na VM nie — dokładnie ten objaw: `Sesja: pobieranie` + `HTTP 401`.

**Szybka naprawa (bez rebuildu):** skopiuj lokalną sesję na serwer:

```bash
# lokalnie, w katalogu VintAgent
scp backend/data/session.json USER@IP_SERWERA:~/VintAgent/backend/data/session.json

# na serwerze
cd ~/VintAgent && docker compose restart
```

Albo w panelu: przycisk **Wklej** obok statusu sesji → wklej cały nagłówek `Cookie` z lokalnej
przeglądarki (DevTools → Network → vinted.pl → Request Headers → Cookie).

Po zaimportowaniu HTTP refresh sam utrzyma sesję tygodniami. Chromium startuje **na żądanie**, nie w pętli czasowej, więc w normalnej pracy proces aplikacji zajmuje
tyle co samo FastAPI. Na czas bootstrapu (kilka sekund) dochodzi ~250 MB RAM, a `BROWSER_MIN_INTERVAL_SECONDS`
pilnuje, żeby nieudane próby nie zamieniły się w pętlę uruchomień. Sesją opiekuje się dodatkowo
watchdog (`app/session_keeper.py`), który co 5 minut sprawdza jej ważność, więc odnowienie następuje
zanim wątki zobaczą błąd.

W obrazie ląduje tylko *headless shell* Chromium (połowa rozmiaru pełnej przeglądarki, dokładnie to,
czego używa `launch(headless=True)`), a `docker-compose.yml` podnosi `shm_size` do 256 MB — przy
domyślnych 64 MB Dockera karta Chromium potrafi się wywrócić. Gotowy obraz to ~1,5 GB dysku przy
~60 MB RAM w spoczynku.

Ponieważ Vinted rotuje oba tokeny naraz, odnowieniem zajmuje się tylko jeden wątek — pozostałe czekają
i podchwytują nowe cookies ze wspólnego magazynu (`app/session_store.py`).

Stan sesji widać w pasku nawigacji (`Sesja: …`); kliknięcie wymusza odnowienie przeglądarką.

Testy tej warstwy (offline, bez ruchu do Vinted):

```bash
cd backend && python scripts/session_test.py
```

## Statystyki

Każdy link jest osobnym menedżerem: kliknięcie karty na dashboardzie otwiera widok ze statystykami.

- **Znalezione ogłoszenia w czasie** — kubełki godzinowe za 6 h / 24 h / 3 dni / 7 dni.
- **O której godzinie wystawiane są ogłoszenia** — rozkład dobowy liczony z czasu publikacji oferty
  (nie z momentu wykrycia), w czasie lokalnym przeglądarki.
- Kafelki: znalezione łącznie / w ostatniej dobie, średnia na godzinę, liczba sprawdzeń i błędów.

Dane to wyłącznie liczniki w kubełkach godzinowych trzymane w `data.json` (`STATS_RETENTION_HOURS`,
domyślnie 7 dni) — treści ogłoszeń nadal nie ma w UI ani w bazie, trafiają tylko na Telegram.

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
