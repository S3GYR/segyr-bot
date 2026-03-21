"""LiteLLM provider — supports Ollama, OpenAI, Anthropic, and many more."""

from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger

from core.cache.llm_cache import get_cached_response, set_cached_response
from core.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class LiteLLMProvider(LLMProvider):
    """LLM provider using LiteLLM as a unified interface."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "ollama/llama3.2",
    ):
        super().__init__(api_key=api_key, api_base=api_base)
        self._default_model = default_model

    def get_default_model(self) -> str:
        return self._default_model

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
            model_id = model or self._default_model

            # Cache only plain-text generations (no tool definitions) to avoid
            # changing tool-calling behavior.
            cache_prompt = None
            if not tools and tool_choice is None:
                cache_payload = {
                    "model": model_id,
                    "messages": clean_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                cache_prompt = json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, default=str)
                cached = get_cached_response(cache_prompt)
                if cached is not None:
                    return LLMResponse(content=cached, finish_reason="stop")

            kwargs: dict[str, Any] = {
                "model": model_id,
                "messages": clean_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if tools:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

            response = await litellm.acompletion(**kwargs)
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

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
            )

        except Exception as exc:
            logger.error("LiteLLM error: {}", exc)
            return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")
