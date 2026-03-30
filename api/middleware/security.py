from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config.settings import settings
from core.logging import logger
from core.redis.client import get_redis

PROTECTED_PATH_PREFIXES = ("/chat", "/repair", "/dashboard")


def _is_rate_limited_path(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in PROTECTED_PATH_PREFIXES)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _resolve_identity(request: Request) -> str:
    api_token = (request.headers.get(settings.api_token_header) or "").strip()
    if api_token:
        return f"token:{_fingerprint(api_token)}"

    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
        if bearer:
            return f"bearer:{_fingerprint(bearer)}"

    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def _increment_rate_limit(identity: str) -> tuple[int, int]:
    window_seconds = max(1, int(settings.global_rate_limit_window_seconds))
    bucket = int(time.time()) // window_seconds
    redis_key = f"segyr:ratelimit:{identity}:{bucket}"
    redis = get_redis()
    current = int(redis.incr(redis_key))
    if current == 1:
        redis.expire(redis_key, window_seconds + 2)
    ttl = int(redis.ttl(redis_key) or 0)
    retry_after = ttl if ttl > 0 else window_seconds
    return current, retry_after


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed global rate limiter for critical endpoints."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not settings.global_rate_limit_enabled or settings.test_mode:
            return await call_next(request)

        if not _is_rate_limited_path(request.url.path):
            return await call_next(request)

        identity = _resolve_identity(request)
        try:
            count, retry_after = await asyncio.to_thread(_increment_rate_limit, identity)
        except RedisError as exc:
            logger.warning("global rate limit redis error path={} err={}", request.url.path, exc)
            if settings.global_rate_limit_fail_closed:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Rate limiter indisponible"},
                    headers={"Retry-After": "5"},
                )
            return await call_next(request)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("global rate limit failure path={} err={}", request.url.path, exc)
            return await call_next(request)

        limit = max(1, int(settings.global_rate_limit_max_requests))
        if count > limit:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit global atteint ({limit}/{settings.global_rate_limit_window_seconds}s)"},
                headers={"Retry-After": str(max(1, retry_after))},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject strict security headers on every HTTP response."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)

        hsts = f"max-age={int(settings.http_hsts_max_age)}; includeSubDomains"
        response.headers.setdefault("Strict-Transport-Security", hsts)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Content-Security-Policy", settings.http_content_security_policy)
        response.headers.setdefault("Referrer-Policy", settings.http_referrer_policy)
        return response
