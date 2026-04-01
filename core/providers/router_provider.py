from __future__ import annotations

import time
from typing import Any

from loguru import logger

from core.providers.base import LLMProvider, LLMResponse
from core.utils.circuit_breaker import CircuitOpenError


def _extract_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                        return str(item.get("text"))
    return ""


class MultiLLMRouter(LLMProvider):
    def __init__(
        self,
        primary: LLMProvider,
        secondary: LLMProvider | None = None,
        fast_model: str | None = None,
        mode: str = "quality",
    ) -> None:
        super().__init__(api_key=None, api_base=None)
        self.primary = primary
        self.secondary = secondary
        self.fast_model = fast_model
        self.mode = mode or "auto"
        self._stats: dict[str, Any] = {
            "counts": {},
            "fallbacks": 0,
            "latencies_ms": {},
        }

    def set_mode(self, mode: str) -> None:
        if mode not in {"fast", "quality", "auto"}:
            mode = "auto"
        self.mode = mode

    def get_default_model(self) -> str:
        return self.primary.get_default_model()

    def _record(self, name: str, elapsed_ms: float, fallback: bool) -> None:
        counts = self._stats["counts"]
        latencies = self._stats["latencies_ms"]
        counts[name] = counts.get(name, 0) + 1
        latencies[name] = latencies.get(name, 0.0) + elapsed_ms
        if fallback:
            self._stats["fallbacks"] += 1

    def get_metrics(self) -> dict[str, Any]:
        return self._stats

    def _select_mode(self, messages: list[dict[str, Any]], override: str | None) -> str:
        if override in {"fast", "quality", "auto"}:
            return override
        mode = self.mode or "auto"
        if mode == "auto":
            text = _extract_user_text(messages)
            if len(text) > 200:
                return "quality"
            keywords = ("analyse", "rapport", "complexe")
            lowered = text.lower()
            if any(k in lowered for k in keywords):
                return "quality"
            return "fast"
        return mode

    async def _try_provider(
        self,
        provider: LLMProvider,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        tag: str,
        fallback: bool,
        mode: str,
    ) -> LLMResponse | None:
        started = time.perf_counter()
        try:
            resp = await provider.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
        except CircuitOpenError as exc:
            logger.error("LLM circuit open provider={} mode={} model={}: {}", tag, mode, model or provider.get_default_model(), exc)
            return None
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.warning("LLM error provider={} mode={} model={} -> {}", tag, mode, model or provider.get_default_model(), (str(exc) or "")[:200])
            return None

        elapsed_ms = (time.perf_counter() - started) * 1000
        self._record(tag, elapsed_ms, fallback)
        if resp.finish_reason == "error":
            logger.warning("LLM returned error provider={} mode={} model={}", tag, mode, model or provider.get_default_model())
            return None
        logger.info(
            "LLM call success mode={} provider_tag={} fallback={} latency_ms={}",
            mode,
            tag,
            fallback,
            round(elapsed_ms, 2),
        )
        return resp

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> LLMResponse:
        effective_mode = self._select_mode(messages, mode)

        candidates: list[tuple[LLMProvider, str | None, str]] = []

        if effective_mode == "fast":
            if self.fast_model:
                candidates.append((self.primary, self.fast_model, "primary_fast"))
            else:
                candidates.append((self.primary, model, "primary"))
            if self.secondary is not None:
                candidates.append((self.secondary, None, "secondary"))
        elif effective_mode == "quality":
            candidates.append((self.primary, model, "primary"))
            if self.secondary is not None:
                candidates.append((self.secondary, None, "secondary"))
        else:  # auto fallback safety
            candidates.append((self.primary, model, "primary"))
            if self.secondary is not None:
                candidates.append((self.secondary, None, "secondary"))

        last_resp: LLMResponse | None = None
        for idx, (prov, model_override, tag) in enumerate(candidates):
            fallback = idx > 0
            resp = await self._try_provider(
                prov,
                messages=messages,
                tools=tools,
                model=model_override or model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                tag=tag,
                fallback=fallback,
                mode=effective_mode,
            )
            if resp:
                return resp
            last_resp = resp or last_resp

        if last_resp:
            return last_resp
        return LLMResponse(content="LLM unavailable", finish_reason="error")


__all__ = ["MultiLLMRouter"]
