# ---- Stage 1: frontend ----
FROM node:24-alpine AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: API + Chromium CDP (CookieScraper style) ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_DIR=/app/static \
    DATA_FILE=/app/data/data.json \
    SESSION_FILE=/app/data/session.json \
    BROWSER_PROFILE_DIR=/app/data/chrome_cdp \
    CHROME_CDP_URL=http://127.0.0.1:9222 \
    CHROME_CDP_PORT=9222 \
    CHROME_DOCKER=1 \
    CHROME_MANAGED_BY_ENTRYPOINT=1 \
    DISPLAY=:99 \
    BROWSER_BOOTSTRAP_ENABLED=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
        fonts-dejavu-core \
        ca-certificates \
        xvfb \
        wget \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

COPY backend/app ./app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY --from=frontend-builder /frontend/dist ./static

RUN mkdir -p /app/data

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
