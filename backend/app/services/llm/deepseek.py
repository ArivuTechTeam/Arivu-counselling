"""
DeepSeek provider — our primary model.

DeepSeek exposes an OpenAI-compatible /chat/completions endpoint, so we call it
with plain httpx (no OpenAI SDK, no LangChain — per the locked stack). We ask
for a JSON object response so the model returns machine-parseable output.
"""

from __future__ import annotations

import httpx

from app.lib.config import get_settings
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

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"DeepSeek returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"DeepSeek request failed: {exc}") from exc

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected DeepSeek response shape: {data}") from exc
