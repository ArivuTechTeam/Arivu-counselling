"""Stage-aware LLM router with an optional cross-provider fallback."""

from __future__ import annotations

import json

from app.lib.config import get_settings
from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.gemini import GeminiProvider
from app.services.ai_call_logging import ai_provider_attempt

__all__ = ["LLMError", "LLMProvider", "complete_with_fallback", "get_providers"]


def get_providers(preferred_provider: str | None = None) -> list[LLMProvider]:
    settings = get_settings()
    available: dict[str, LLMProvider] = {}
    if settings.deepseek_api_key:
        available["deepseek"] = DeepSeekProvider()
    if settings.gemini_api_key:
        available["gemini"] = GeminiProvider()
    preferred = preferred_provider or "gemini"
    fallback = getattr(settings, "ai_fallback_provider", "gemini")
    order = list(dict.fromkeys([preferred, fallback, "deepseek", "gemini"]))
    providers = [available[name] for name in order if name in available]
    if not providers:
        raise LLMError(
            "No LLM provider configured — set GEMINI_API_KEY or DEEPSEEK_API_KEY."
        )
    return providers


def complete_with_fallback(
    system_prompt: str,
    user_prompt: str,
    *,
    preferred_provider: str | None = None,
) -> tuple[str, str]:
    """
    Try each provider in order. Since every current caller requests a JSON
    object, malformed/non-object output is also a provider failure and can use
    the next provider instead of consuming a separate correction call.
    """
    failures: list[str] = []
    for index, provider in enumerate(get_providers(preferred_provider)):
        try:
            with ai_provider_attempt(was_fallback=index > 0):
                content = provider.complete(system_prompt, user_prompt)
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise LLMError("returned a non-object JSON value")
            return content, provider.name
        except json.JSONDecodeError:
            failures.append(f"{provider.name} returned invalid JSON")
        except LLMError as exc:
            failures.append(f"{provider.name}: {exc}")
    raise LLMError("All LLM providers failed → " + " | ".join(failures))
