"""LiteLLM provider — supports Ollama, OpenAI, Anthropic, and many more."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from loguru import logger

from core.cache.llm_cache import get_cached_response, set_cached_response
from core.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from core.utils.circuit_breaker import CircuitBreaker, CircuitOpenError


class LiteLLMProvider(LLMProvider):
    """LLM provider using LiteLLM as a unified interface."""

    _TRANSIENT_ERROR_MARKERS = (
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
    )
    _RETRY_DELAYS_S = (1, 2, 4)

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "ollama/llama3.2",
        fallback_model: str | None = None,
        timeout_s: float = 120.0,
        retry_attempts: int = 2,
    ):
        super().__init__(api_key=api_key, api_base=api_base)
        self._default_model = default_model
        self._fallback_model = fallback_model
        self._timeout_s = max(1.0, float(timeout_s))
        self._retry_attempts = max(1, int(retry_attempts))
        self._breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout_s=30.0,
            half_open_max_calls=1,
            name="llm",
        )

    def get_default_model(self) -> str:
        return self._default_model

    @classmethod
    def _is_retryable_error(cls, exc: Exception) -> bool:
        err = str(exc).lower()
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def _completion_with_retry(self, litellm_module: Any, kwargs: dict[str, Any], model_id: str):
        delays = self._RETRY_DELAYS_S[: max(0, self._retry_attempts - 1)]
        last_exc: Exception | None = None

        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await litellm_module.acompletion(**kwargs)
            except Exception as exc:  # pragma: no cover - runtime safety
                last_exc = exc
                if attempt >= self._retry_attempts or not self._is_retryable_error(exc):
                    break
                delay = delays[min(attempt - 1, len(delays) - 1)] if delays else 1
                logger.warning(
                    "LiteLLM transient error model={} attempt={}/{} -> retry in {}s ({})",
                    model_id,
                    attempt,
                    self._retry_attempts,
                    delay,
                    (str(exc) or "")[:180],
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LiteLLM completion failed without explicit exception")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        try:
            import litellm

            clean_messages = self._sanitize_empty_content(messages)
            primary_model = model or self._default_model
            candidate_models = [primary_model]
            if self._fallback_model and self._fallback_model != primary_model:
                candidate_models.append(self._fallback_model)

            # Cache only plain-text generations (no tool definitions) to avoid
            # changing tool-calling behavior.
            cache_prompt = None
            if not tools and tool_choice is None:
                cache_payload = {
                    "model": primary_model,
                    "messages": clean_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                cache_prompt = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, default=str)
                cached = get_cached_response(cache_prompt)
                if cached is not None:
                    return LLMResponse(content=cached, finish_reason="stop")

            last_exc: Exception | None = None
            for idx, model_id in enumerate(candidate_models):
                kwargs: dict[str, Any] = {
                    "model": model_id,
                    "messages": clean_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "timeout": min(self._timeout_s, 5.0),
                }
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.api_base:
                    kwargs["api_base"] = self.api_base
                if tools:
                    kwargs["tools"] = tools
                if tool_choice is not None:
                    kwargs["tool_choice"] = tool_choice

                async def _call_model() -> Any:
                    return await self._completion_with_retry(litellm, kwargs, model_id=model_id)

                try:
                    response = await self._breaker.call_async(
                        _call_model,
                        timeout_s=kwargs["timeout"],
                        max_attempts=min(3, self._retry_attempts + 1),
                        backoff_base_s=0.5,
                    )
                    choice = response.choices[0]
                    msg = choice.message
                    content = msg.content or None
                    finish_reason = choice.finish_reason or "stop"

                    tool_calls: list[ToolCallRequest] = []
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            try:
                                args = json.loads(tc.function.arguments or "{}")
                            except Exception:
                                args = {}
                            tool_calls.append(ToolCallRequest(
                                id=tc.id or str(uuid.uuid4()),
                                name=tc.function.name,
                                arguments=args,
                            ))

                    usage = {}
                    if response.usage:
                        usage = {
                            "prompt_tokens": response.usage.prompt_tokens or 0,
                            "completion_tokens": response.usage.completion_tokens or 0,
                        }

                    if tool_calls:
                        finish_reason = "tool_calls"

                    if cache_prompt and content:
                        set_cached_response(cache_prompt, content, ttl=3600)

                    if idx > 0:
                        logger.warning("LiteLLM fallback model used: {}", model_id)

                    return LLMResponse(
                        content=content,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                        usage=usage,
                    )
                except CircuitOpenError as exc:
                    last_exc = exc
                    logger.error("LiteLLM circuit open, skipping model {}", model_id)
                except Exception as exc:  # pragma: no cover - runtime safety
                    last_exc = exc
                    if idx + 1 < len(candidate_models):
                        logger.warning(
                            "LiteLLM primary model failed ({}), trying fallback model {}",
                            (str(exc) or "")[:200],
                            candidate_models[idx + 1],
                        )
                        continue
                    raise

        except Exception as exc:
            logger.error("LiteLLM error: {}", exc)
            return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")
