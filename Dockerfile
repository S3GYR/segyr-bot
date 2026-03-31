FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS backend-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
  && pip wheel --wheel-dir=/wheels -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app \
  && useradd --system --gid app --create-home app

COPY --from=backend-builder /wheels /wheels
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
  && pip install --no-index --find-links=/wheels -r requirements.txt \
  && rm -rf /wheels

COPY core/ core/
COPY agents/ agents/
COPY modules/ modules/
COPY tools/ tools/
COPY api/ api/
COPY config/ config/
COPY segyr_bot/ segyr_bot/
COPY run_redis_e2e.py ./
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN mkdir -p /app/logs /app/workspace \
  && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["python", "-m", "segyr_bot.gateway"]
