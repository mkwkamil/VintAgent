# VintAgent

Vinted URL manager + Telegram. Scraped items never appear in the UI.

## Sesja (Chrome CDP — jak CookieScraper)

Zamiast Playwright headless używamy **prawdziwego Google Chrome** z remote debugging:

1. Backend startuje Chrome z osobnym profilem (`data/chrome_cdp/`)
2. Czyta cookies przez CDP (`Network.getAllCookies`)
3. Scrapery (`curl_cffi`) używają tych cookies
4. HTTP refresh utrzymuje JWT; przy 403 — ponowny sync z Chrome

Pierwsze uruchomienie: otworzy się okno Chrome → zaloguj się na vinted.pl → backend sam wykryje `access_token_web` (bez Enter w terminalu).

## Lokalnie

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# DATA_FILE=data/data.json
# SESSION_FILE=data/session.json

uvicorn app.main:app --reload --port 8000
```

Wymaga zainstalowanego **Google Chrome**.

## Docker

Obraz nie instaluje Chrome — seed `session.json` albo Wklej Cookie. CDP działa najlepiej lokalnie na Macu.

```bash
docker compose up --build -d
```
