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
from app.services.llm.gemini_http import post_gemini


class GeminiProvider(LLMProvider):
    name = "gemini"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set — cannot call Gemini.")

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
            resp = post_gemini(
                settings=settings,
                model=settings.gemini_model,
                payload=payload,
                headers=headers,
                timeout=120.0,
            )
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Gemini returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("Gemini request failed.") from exc

        data = resp.json()
        try:
            # If the model refuses on safety grounds there may be no parts —
            # that surfaces here as a KeyError and becomes a fallback trigger.
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError("Gemini returned an unexpected or empty response.") from exc
