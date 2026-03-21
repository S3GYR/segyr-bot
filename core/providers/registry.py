"""Provider registry — resolve provider from model string or config."""

from __future__ import annotations

from loguru import logger

from core.providers.base import LLMProvider


def get_provider(
    model: str,
    api_key: str | None = None,
    api_base: str | None = None,
) -> LLMProvider:
    """
    Return the appropriate LLMProvider for the given model string.

    Model prefixes:
      - "ollama/..."         → LiteLLM (local Ollama)
      - "anthropic/..."      → LiteLLM (Anthropic)
      - "openai/..."         → LiteLLM (OpenAI)
      - "groq/..."           → LiteLLM (Groq)
      - anything else        → LiteLLM (pass-through)
    """
    from core.providers.litellm_provider import LiteLLMProvider

    logger.info("Using LiteLLM provider for model: {}", model)
    return LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=model,
    )
