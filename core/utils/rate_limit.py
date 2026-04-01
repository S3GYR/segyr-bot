from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

try:
    from core.redis.client import redis_incr
except Exception:  # pragma: no cover - fallback
    redis_incr = None  # type: ignore


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int, prefix: str = "rl") -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.prefix = prefix
        self._local_buckets: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    def _key(self, identity: str) -> str:
        return f"{self.prefix}:{identity}"

    async def allow(self, identity: str) -> bool:
        if redis_incr:
            key = self._key(identity)
            count = await redis_incr(key, ttl_seconds=self.window_seconds, timeout_s=1.0)
            if count is None:
                return False
            return count <= self.max_requests
        # Fallback memory bucket
        now = time.time()
        window_start = now - self.window_seconds
        async with self._lock:
            bucket = self._local_buckets.setdefault(identity, [])
            # prune
            bucket = [ts for ts in bucket if ts >= window_start]
            bucket.append(now)
            self._local_buckets[identity] = bucket
            return len(bucket) <= self.max_requests


__all__ = ["RateLimiter"]
