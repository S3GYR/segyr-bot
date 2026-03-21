from __future__ import annotations

from redis import Redis
from redis.exceptions import RedisError

from config.settings import settings
from loguru import logger

_REDIS_WARNED = False


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
