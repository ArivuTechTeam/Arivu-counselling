"""
Gemini provider — Google's Generative Language API.

Same LLMProvider interface as DeepSeek, so the fallback router treats them
interchangeably. We ask for a JSON response (responseMimeType) so the output
is machine-parseable, exactly like the DeepSeek path.
"""

from __future__ import annotations

import httpx

from app.lib.config import get_settings
from app.services.llm.base import LLMError, LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set — cannot call Gemini.")

        url = (
            f"{settings.gemini_base_url}/models/"
            f"{settings.gemini_model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "x-goog-api-key": settings.gemini_api_key,
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"Gemini returned {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc

        data = resp.json()
        try:
            # If the model refuses on safety grounds there may be no parts —
            # that surfaces here as a KeyError and becomes a fallback trigger.
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(
                f"Unexpected Gemini response (blocked or empty?): {str(data)[:300]}"
            ) from exc
