from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

from redis import Redis
from redis.exceptions import RedisError

from config.settings import settings
from core.utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from loguru import logger

_REDIS_WARNED = False
_T = TypeVar("_T")
_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_s=30.0, half_open_max_calls=1, name="redis")


def _build_client() -> Redis:
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
        health_check_interval=15,
    )
    try:
        if settings.redis_enabled:
            client.ping()
            logger.info("Redis connecté: {}", settings.REDIS_URL)
    except RedisError as exc:
        _warn_redis_down(exc)
    return client


def _warn_redis_down(exc: Exception) -> None:
    global _REDIS_WARNED
    if not _REDIS_WARNED:
        logger.warning("Redis indisponible (fallback local): {}", exc)
        _REDIS_WARNED = True


redis_client = _build_client()


def get_redis() -> Redis:
    return redis_client


async def _redis_with_retry(fn: Callable[[], _T], timeout_s: float = 1.0, max_attempts: int = 3) -> _T:
    loop = asyncio.get_running_loop()

    async def _call() -> _T:
        return await loop.run_in_executor(None, fn)

    return await _breaker.call_async(_call, timeout_s=timeout_s, max_attempts=max_attempts, backoff_base_s=0.5)


async def redis_ping(timeout_s: float = 1.0) -> bool:
    try:
        await _redis_with_retry(redis_client.ping, timeout_s=timeout_s)
        return True
    except CircuitOpenError as exc:
        logger.error("Redis circuit open: {}", exc)
        return False
    except Exception as exc:
        logger.warning("Redis ping failed: {}", exc)
        return False


async def redis_get(key: str, timeout_s: float = 1.0) -> Any:
    try:
        return await _redis_with_retry(partial(redis_client.get, key), timeout_s=timeout_s)
    except Exception as exc:
        logger.warning("Redis get failed key={}: {}", key, exc)
        return None


async def redis_set(key: str, value: Any, ex: int | None = None, timeout_s: float = 1.0) -> bool:
    try:
        await _redis_with_retry(partial(redis_client.set, key, value, ex=ex), timeout_s=timeout_s)
        return True
    except Exception as exc:
        logger.warning("Redis set failed key={}: {}", key, exc)
        return False


async def redis_publish(channel: str, message: str, timeout_s: float = 1.0) -> bool:
    try:
        await _redis_with_retry(partial(redis_client.publish, channel, message), timeout_s=timeout_s)
        return True
    except Exception as exc:
        logger.warning("Redis publish failed channel={}: {}", channel, exc)
        return False


async def redis_incr(key: str, ttl_seconds: int, timeout_s: float = 1.0) -> int | None:
    loop = asyncio.get_running_loop()

    def _incr_and_expire() -> int:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, ttl_seconds)
        return count

    try:
        return await _breaker.call_async(
            lambda: asyncio.wait_for(loop.run_in_executor(None, _incr_and_expire), timeout=timeout_s),
            timeout_s=timeout_s,
            max_attempts=3,
            backoff_base_s=0.2,
        )
    except CircuitOpenError as exc:
        logger.error("Redis circuit open on incr {}: {}", key, exc)
        return None
    except Exception as exc:
        logger.warning("Redis incr failed key={}: {}", key, exc)
        return None
