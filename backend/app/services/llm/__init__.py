"""
LLM router with fallback.

get_providers() builds the ordered list from whichever keys are configured:
Gemini is preferred (primary) when GEMINI_API_KEY is set, with DeepSeek as the
fallback. If only one key is present, that provider is used alone.
"""

from __future__ import annotations

from app.lib.config import get_settings
from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.gemini import GeminiProvider
from app.services.ai_call_logging import ai_provider_attempt

__all__ = ["LLMError", "LLMProvider", "complete_with_fallback", "get_providers"]


def get_providers() -> list[LLMProvider]:
    settings = get_settings()
    providers: list[LLMProvider] = []
    # Gemini primary (if configured), then DeepSeek fallback (if configured).
    if settings.gemini_api_key:
        providers.append(GeminiProvider())
    if settings.deepseek_api_key:
        providers.append(DeepSeekProvider())
    if not providers:
        raise LLMError(
            "No LLM provider configured — set GEMINI_API_KEY or DEEPSEEK_API_KEY."
        )
    return providers


def complete_with_fallback(system_prompt: str, user_prompt: str) -> tuple[str, str]:
    """
    Try each provider in order. Return (content, provider_name) from the first
    that succeeds. Raise LLMError with all the failures if none do.
    """
    failures: list[str] = []
    for index, provider in enumerate(get_providers()):
        try:
            with ai_provider_attempt(was_fallback=index > 0):
                return provider.complete(system_prompt, user_prompt), provider.name
        except LLMError as exc:
            failures.append(f"{provider.name}: {exc}")
    raise LLMError("All LLM providers failed → " + " | ".join(failures))
