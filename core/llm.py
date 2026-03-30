from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

import httpx
from loguru import logger

from config.settings import settings


class LLMClientError(RuntimeError):
    """Erreur LLM normalisée avec payload exploitable côté API."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        super().__init__(str(payload.get("error") or "LLM failure"))


class LLMClient:
    """Client LLM robuste orienté Ollama natif (/api/chat + fallback /api/generate)."""

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = self._normalize_model_name(model or settings.llm_model)
        self.fallback_model = self._normalize_model_name(settings.llm.fallback_model)
        self.mode = settings.llm.mode
        self.api_key = api_key or settings.llm_api_key
        self.max_tokens = int(min(max(settings.llm_max_tokens, 500), 800))
        self.temperature = float(min(max(settings.llm.temperature, 0.1), 0.2))
        self.timeout = settings.llm_timeout
        self.retry_attempts = max(1, int(settings.llm.retry_attempts))
        self.cache_ttl = settings.llm_cache_ttl_seconds
        self._cache: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._last_error: Dict[str, Any] | None = None

    async def chat(self, messages: List[Dict[str, Any]]) -> str:
        if settings.test_mode or os.getenv("SEGYR_TEST_MODE", "").lower() == "true":
            return "mocked response"

        self._last_error = None
        selected_model = self._select_primary_model()
        fallback_used = False

        cache_key = (selected_model, repr(messages))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        model_candidates = [selected_model]
        if self.fallback_model and self.fallback_model not in model_candidates:
            model_candidates.append(self.fallback_model)

        last_error = "LLM failure"
        for model_index, model_name in enumerate(model_candidates):
            fallback_used = model_index > 0
            if fallback_used:
                logger.warning("LLM timeout/error -> fallback triggered: model={}", model_name)

            for attempt in range(1, self.retry_attempts + 1):
                try:
                    started = time.perf_counter()
                    logger.info(
                        "LLM request started model={} endpoint=/api/chat attempt={}",
                        model_name,
                        attempt,
                    )
                    content = await self._call_ollama_chat(model_name, messages)
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    logger.info("LLM response received ({} ms) model={}", elapsed_ms, model_name)
                    self._cache_set((model_name, repr(messages)), content or "")
                    if fallback_used and model_name != selected_model:
                        self._cache_set((selected_model, repr(messages)), content or "")
                    return content or ""
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "unknown"
                    last_error = f"LLM HTTP error ({status_code})"
                    logger.warning(
                        "LLM HTTPStatusError model={} status={} attempt={}",
                        model_name,
                        status_code,
                        attempt,
                    )
                    if exc.response is not None and exc.response.status_code == 404:
                        try:
                            started = time.perf_counter()
                            logger.info(
                                "LLM endpoint /api/chat unavailable -> trying /api/generate model={}",
                                model_name,
                            )
                            content = await self._call_ollama_generate(model_name, messages)
                            elapsed_ms = int((time.perf_counter() - started) * 1000)
                            logger.info(
                                "LLM response received ({} ms) model={} endpoint=/api/generate",
                                elapsed_ms,
                                model_name,
                            )
                            self._cache_set((model_name, repr(messages)), content or "")
                            if fallback_used and model_name != selected_model:
                                self._cache_set((selected_model, repr(messages)), content or "")
                            return content or ""
                        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectError) as fallback_exc:
                            last_error = f"{last_error} | generate fallback failed: {fallback_exc.__class__.__name__}"

                    if not self._can_retry_http(exc) or attempt >= self.retry_attempts:
                        break
                except httpx.ReadTimeout:
                    last_error = "LLM timeout"
                    logger.warning(
                        "LLM timeout -> fallback triggered model={} attempt={} timeout={}s",
                        model_name,
                        attempt,
                        round(self.timeout, 1),
                    )
                    if attempt >= self.retry_attempts:
                        break
                except httpx.ConnectError:
                    last_error = "LLM connection error"
                    logger.warning("LLM connect error model={} attempt={}", model_name, attempt)
                    if attempt >= self.retry_attempts:
                        break
                except Exception as exc:  # pragma: no cover - runtime safety
                    last_error = f"Unexpected LLM error: {exc}"
                    logger.exception("Unexpected LLM failure model={}", model_name)
                    break

        payload = {
            "error": last_error,
            "fallback_used": fallback_used,
            "provider": settings.llm_provider,
            "model": selected_model,
            "fallback_model": self.fallback_model,
        }
        self._last_error = payload
        raise LLMClientError(payload)

    async def _call_ollama_chat(self, model_name: str, messages: List[Dict[str, Any]]) -> str:
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        url = f"{self.base_url}/api/chat"
        headers = self._headers()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return self._extract_content(data)

    async def _call_ollama_generate(self, model_name: str, messages: List[Dict[str, Any]]) -> str:
        payload = {
            "model": model_name,
            "prompt": self._messages_to_prompt(messages),
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        url = f"{self.base_url}/api/generate"
        headers = self._headers()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return self._extract_content(data)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _extract_content(self, data: Dict[str, Any]) -> str:
        if isinstance(data.get("message"), dict):
            return str(data.get("message", {}).get("content") or "")
        if "response" in data:
            return str(data.get("response") or "")
        return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))

    def _messages_to_prompt(self, messages: List[Dict[str, Any]]) -> str:
        chunks: List[str] = []
        for msg in messages:
            role = str(msg.get("role") or "user").upper()
            content = str(msg.get("content") or "").strip()
            if content:
                chunks.append(f"[{role}] {content}")
        chunks.append("[ASSISTANT]")
        return "\n".join(chunks)

    def _normalize_model_name(self, model_name: str) -> str:
        if not model_name:
            return model_name
        if "/" in model_name:
            provider, candidate = model_name.split("/", 1)
            if provider.lower() == "ollama" and candidate:
                return candidate
        return model_name

    def _select_primary_model(self) -> str:
        if self.mode == "fast" and self.fallback_model:
            return self.fallback_model
        return self.model

    def _can_retry_http(self, exc: httpx.HTTPStatusError) -> bool:
        status_code = exc.response.status_code if exc.response is not None else 0
        return status_code >= 500 or status_code == 429

    def get_last_error(self) -> Dict[str, Any] | None:
        return self._last_error

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
