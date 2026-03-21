from __future__ import annotations

import hashlib
from redis.exceptions import RedisError

from config.settings import settings
from core.redis.client import get_redis
from loguru import logger


def get_cache_key(prompt: str) -> str:
    digest = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()
    return f"segyr:cache:{digest}"


def get_cached_response(prompt: str) -> str | None:
    if not settings.redis_enabled or settings.debug:
        return None
    key = get_cache_key(prompt)
    try:
        value = get_redis().get(key)
        if value:
            logger.info("LLM cache HIT")
            return str(value)
        logger.info("LLM cache MISS")
        return None
    except RedisError as exc:
        logger.warning("LLM cache indisponible: {}", exc)
        return None


def set_cached_response(prompt: str, response: str, ttl: int = 3600) -> bool:
    if not settings.redis_enabled or settings.debug:
        return False
    text = (response or "").strip()
    if not text or text.lower() == "traitement en cours":
        return False

    key = get_cache_key(prompt)
    effective_ttl = ttl if ttl > 0 else settings.cache_ttl
    try:
        ok = get_redis().setex(key, effective_ttl, text)
        if ok:
            logger.info("LLM cache STORED")
        return bool(ok)
    except RedisError as exc:
        logger.warning("LLM cache store failed: {}", exc)
        return False
