FROM python:3.12-slim

# System deps
RUN apt-get update \ 
  && apt-get install -y --no-install-recommends curl build-essential \ 
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps
COPY pyproject.toml README.md ./
COPY core/ core/
COPY agents/ agents/
COPY modules/ modules/
COPY tools/ tools/
COPY api/ api/
COPY config/ config/
COPY workspace/ workspace/

RUN pip install --no-cache-dir --upgrade pip \ 
  && pip install --no-cache-dir hatchling \ 
  && pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    UVICORN_WORKERS=4

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
