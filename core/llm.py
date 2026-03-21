from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import httpx
from loguru import logger

from config.settings import settings


class LLMClient:
    """Client minimal OpenAI-compatible (Ollama par défaut)."""

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.max_tokens = settings.llm_max_tokens
        self.timeout = settings.llm_timeout
        self.cache_ttl = settings.llm_cache_ttl_seconds
        self._cache: Dict[Tuple[str, str], Tuple[float, str]] = {}

    async def chat(self, messages: List[Dict[str, Any]]) -> str:
        if settings.test_mode or os.getenv("SEGYR_TEST_MODE", "").lower() == "true":
            return "mocked response"

        cache_key = (self.model, repr(messages))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": self.max_tokens,
        }
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url}/chat/completions"
        logger.debug("LLM chat -> %s", url)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        self._cache_set(cache_key, content or "")
        return content or ""

    def _cache_get(self, key: Tuple[str, str]) -> str | None:
        import time

        if self.cache_ttl <= 0:
            return None
        item = self._cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: Tuple[str, str], value: str) -> None:
        import time

        if self.cache_ttl <= 0:
            return
        self._cache[key] = (time.time() + self.cache_ttl, value)
