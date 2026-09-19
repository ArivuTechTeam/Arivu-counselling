"""
DeepSeek provider — our primary model.

DeepSeek exposes an OpenAI-compatible /chat/completions endpoint, so we call it
with plain httpx (no OpenAI SDK, no LangChain — per the locked stack). We ask
for a JSON object response so the model returns machine-parseable output.
"""

from __future__ import annotations

import time

import httpx

from app.lib.config import get_settings
from app.services.ai_call_logging import log_ai_call
from app.services.llm.base import LLMError, LLMProvider


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        settings = get_settings()
        if not settings.deepseek_api_key:
            raise LLMError("DEEPSEEK_API_KEY is not set — cannot call DeepSeek.")

        url = f"{settings.deepseek_base_url}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,  # low = more consistent, less "creative" wording
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        started_at = time.perf_counter()
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                raw_response = exc.response.json()
            except ValueError:
                raw_response = None
            log_ai_call(
                provider="deepseek", model=settings.deepseek_model, request=payload,
                response=raw_response, was_fallback=False, started_at=started_at,
                error_message=f"HTTP {exc.response.status_code}",
            )
            raise LLMError(f"DeepSeek returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            log_ai_call(
                provider="deepseek", model=settings.deepseek_model, request=payload,
                response=None, was_fallback=False, started_at=started_at,
                error_message=type(exc).__name__,
            )
            raise LLMError("DeepSeek request failed.") from exc

        data = resp.json()
        log_ai_call(
            provider="deepseek", model=settings.deepseek_model, request=payload,
            response=data, was_fallback=False, started_at=started_at,
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError("DeepSeek returned an unexpected response shape.") from exc
