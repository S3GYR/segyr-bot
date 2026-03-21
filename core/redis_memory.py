from __future__ import annotations

import json
from redis.exceptions import RedisError

from config.settings import settings
from core.redis.client import get_redis
from loguru import logger


def _key(chat_id: str) -> str:
    return f"segyr:memory:{chat_id}"


def append_message(chat_id: str, role: str, content: str, max_items: int = 50) -> bool:
    if not settings.redis_enabled:
        return False
    payload = {
        "role": role,
        "content": content,
    }
    key = _key(chat_id)
    try:
        redis = get_redis()
        redis.rpush(key, json.dumps(payload, ensure_ascii=False))
        redis.ltrim(key, -max_items, -1)
        return True
    except RedisError as exc:
        logger.warning("Redis memory append failed: {}", exc)
        return False


def get_history(chat_id: str, limit: int = 10) -> list[dict[str, str]]:
    if not settings.redis_enabled or limit <= 0:
        return []
    key = _key(chat_id)
    try:
        raw = get_redis().lrange(key, -limit, -1)
    except RedisError as exc:
        logger.warning("Redis memory read failed: {}", exc)
        return []

    items: list[dict[str, str]] = []
    for row in raw:
        try:
            obj = json.loads(row)
            role = str(obj.get("role", "")).strip()
            content = str(obj.get("content", "")).strip()
            if role and content:
                items.append({"role": role, "content": content})
        except Exception:
            continue
    return items
