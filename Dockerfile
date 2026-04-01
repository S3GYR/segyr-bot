FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8090

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8090

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-c", "gunicorn.conf.py", "segyr_bot.gateway:app"]
