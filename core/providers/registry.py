"""Provider registry — resolve provider from model string or config."""

from __future__ import annotations

from loguru import logger

from core.providers.base import LLMProvider
from core.providers.router_provider import MultiLLMRouter

_KNOWN_PREFIXES = ("ollama/", "openai/", "anthropic/", "groq/")


def _normalize_model(model: str, provider: str | None = None) -> str:
    raw_model = (model or "").strip()
    if not raw_model:
        return "ollama/llama3.2"

    if raw_model.startswith(_KNOWN_PREFIXES):
        return raw_model

    provider_name = (provider or "").strip().lower()
    if provider_name in {"", "litellm"}:
        # If provider is not explicit, keep compatibility with existing default:
        # model values without prefix are assumed to be Ollama model ids.
        provider_name = "ollama"

    if provider_name in {"ollama", "openai", "anthropic", "groq"}:
        return f"{provider_name}/{raw_model}"

    # Unknown provider value: still return a model accepted by LiteLLM.
    logger.warning("Unknown LLM provider '{}', defaulting model prefix to ollama", provider_name)
    return f"ollama/{raw_model}"


def get_provider(
    model: str,
    provider: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> LLMProvider:
    """
    Return the appropriate LLMProvider for the given model string.

    SEGYR v2 unifies provider calls through LiteLLM.
    The model is normalized to a provider-prefixed id expected by LiteLLM,
    for example:
      - ollama/qwen3.5:9b
      - openai/gpt-4o-mini
    """
    from config.settings import settings
    from core.providers.litellm_provider import LiteLLMProvider

    normalized_model = _normalize_model(model, provider=provider)
    logger.info("Using LiteLLM provider={} model={}", (provider or "auto"), normalized_model)

    primary = LiteLLMProvider(
        api_key=api_key,
        api_base=api_base,
        default_model=normalized_model,
        fallback_model=_normalize_model(settings.llm.fallback_model, provider=provider),
        timeout_s=settings.llm.timeout,
        retry_attempts=settings.llm.retry_attempts,
    )

    secondary_provider: LLMProvider | None = None
    if settings.llm.secondary_model:
        secondary_provider = LiteLLMProvider(
            api_key=settings.llm.secondary_api_key or None,
            api_base=settings.llm.secondary_api_base or None,
            default_model=_normalize_model(settings.llm.secondary_model, provider=settings.llm.secondary_provider),
            fallback_model=None,
            timeout_s=settings.llm.timeout,
            retry_attempts=settings.llm.retry_attempts,
        )

    if secondary_provider or settings.llm.fast_model:
        router = MultiLLMRouter(
            primary=primary,
            secondary=secondary_provider,
            fast_model=_normalize_model(settings.llm.fast_model, provider=provider) if settings.llm.fast_model else None,
            mode=settings.llm.mode,
        )
        router.generation = primary.generation
        return router

    return primary
