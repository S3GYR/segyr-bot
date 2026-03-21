from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class RedisClient:
    """Async Redis cache client with safe fallbacks.

    - Uses SEGYR_REDIS_URL by default
    - Never raises blocking exceptions to callers
    - Short timeouts (1s) to protect bot responsiveness
    """

    def __init__(
        self,
        url: str | None = None,
        enabled: bool | None = None,
        default_ttl: int = 300,
        timeout_s: float = 1.0,
    ) -> None:
        env_url = os.getenv("SEGYR_REDIS_URL") or os.getenv("REDIS_URL")
        self.url = url or env_url or "redis://localhost:6379/0"
        self.enabled = _env_bool("SEGYR_REDIS_ENABLED", True) if enabled is None else enabled
        self.default_ttl = default_ttl
        self.timeout_s = timeout_s

        self._client: Any = None
        self._pool: Any = None
        self._warned_down = False

        if self.enabled:
            self._init_client()

    def _init_client(self) -> None:
        try:
            from redis.asyncio import Redis
            from redis.asyncio.connection import ConnectionPool

            self._pool = ConnectionPool.from_url(
                self.url,
                socket_connect_timeout=self.timeout_s,
                socket_timeout=self.timeout_s,
                health_check_interval=15,
                decode_responses=True,
                max_connections=20,
            )
            self._client = Redis(connection_pool=self._pool)
        except Exception as exc:
            self._client = None
            self.enabled = False
            logger.warning("Redis indisponible au démarrage (cache désactivé): {}", exc)

    def _warn_down(self, exc: Exception) -> None:
        if not self._warned_down:
            logger.warning("Redis indisponible, fallback sans cache: {}", exc)
            self._warned_down = True

    async def ping(self) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            ok = await asyncio.wait_for(self._client.ping(), timeout=self.timeout_s)
            self._warned_down = False
            return bool(ok)
        except Exception as exc:
            self._warn_down(exc)
            return False

    async def get(self, key: str) -> str | None:
        if not self.enabled or self._client is None:
            return None
        try:
            value = await asyncio.wait_for(self._client.get(key), timeout=self.timeout_s)
            self._warned_down = False
            if value is None:
                return None
            return str(value)
        except Exception as exc:
            self._warn_down(exc)
            return None

    async def set(self, key: str, value: str, ttl: int = 300) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            ex = ttl if ttl > 0 else self.default_ttl
            ok = await asyncio.wait_for(self._client.set(key, value, ex=ex), timeout=self.timeout_s)
            self._warned_down = False
            return bool(ok)
        except Exception as exc:
            self._warn_down(exc)
            return False

    async def delete(self, key: str) -> bool:
        if not self.enabled or self._client is None:
            return False
        try:
            deleted = await asyncio.wait_for(self._client.delete(key), timeout=self.timeout_s)
            self._warned_down = False
            return bool(deleted)
        except Exception as exc:
            self._warn_down(exc)
            return False
