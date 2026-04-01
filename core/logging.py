from __future__ import annotations

import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict

from fastapi import FastAPI, Request
from loguru import logger

# Force UTF-8 encoding for Windows console output.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Structured JSON logging configuration with request_id enrichment
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _patch_request_id(record: dict[str, Any]) -> None:
    rid = request_id_var.get()
    if rid:
        record["extra"]["request_id"] = rid


logger.remove()
logger.add(
    sink=sys.stdout,
    serialize=True,
    level=os.getenv("SEGYR_LOG_LEVEL", "INFO"),
    enqueue=True,
    backtrace=False,
    diagnose=False,
    patcher=_patch_request_id,
)


def setup_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", 0.1)))
    except Exception:
        # fail silent, do not break API
        logger.warning("Sentry init failed", exc_info=True)


def log_requests(app: FastAPI) -> None:
    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next: Callable):  # type: ignore
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.middleware("http")
    async def _log_requests(request: Request, call_next: Callable):  # type: ignore
        start = time.time()
        response = None
        try:
            response = await call_next(request)
            return response
        except Exception:
            logger.bind(
                event="http_error",
                method=request.method,
                path=request.url.path,
                client=request.client.host if request.client else None,
            ).exception("request failed")
            raise
        finally:
            process_time = time.time() - start
            log_payload: Dict[str, Any] = {
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status": getattr(response, "status_code", None),
                "process_time_ms": round(process_time * 1000, 2),
                "client": request.client.host if request.client else None,
            }
            logger.bind(**log_payload).info("request completed")

    # Prometheus-ready hook placeholder (exporter not included)
    app.state.prometheus_enabled = True


__all__ = ["logger", "log_requests", "setup_sentry"]
