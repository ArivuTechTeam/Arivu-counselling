"""
Structured (JSON-schema-constrained) Gemini calls.

Gemini's `responseSchema` guarantees the model returns JSON matching an exact
shape — so we never parse fragile free-text. This is the backbone of the
blueprint quiz feature: BOTH topic extraction and blueprint generation call
`gemini_json` with a schema and get back a validated dict.

Kept separate from the plain-text `LLMProvider` path because it is Gemini-
specific and schema-driven. Model defaults to the cheap Flash-Lite tier
(config.gemini_blueprint_model), swappable via env with no code change.
"""

from __future__ import annotations

import json

import httpx

from app.lib.config import get_settings
from app.services.llm.base import LLMError


def gemini_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict | None = None,
    *,
    model: str | None = None,
    temperature: float = 0.2,
) -> dict:
    """
    Call Gemini and return the parsed top-level JSON object.

    Pass `schema` to hard-constrain the output shape (best when the shape is
    fixed, e.g. a topic list). Omit it to just force JSON output via
    responseMimeType — better when a field varies in type (e.g. a question's
    correct_answer can be a string, list, or object) — and validate with
    Pydantic afterwards.

    Raises LLMError on missing key, network/HTTP failure, a blocked/empty
    response, or (rarely) non-JSON output.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set — cannot call Gemini.")

    model = model or settings.gemini_blueprint_model
    url = f"{settings.gemini_base_url}/models/{model}:generateContent"
    generation_config: dict = {
        "temperature": temperature,
        "responseMimeType": "application/json",
    }
    if schema is not None:
        generation_config["responseSchema"] = schema
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": generation_config,
    }
    headers = {
        "x-goog-api-key": settings.gemini_api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=180.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"Gemini returned {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Gemini request failed: {exc}") from exc

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError(
            f"Unexpected Gemini response (blocked or empty?): {str(data)[:300]}"
        ) from exc

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini returned non-JSON despite schema: {text[:300]}") from exc

    if not isinstance(parsed, dict):
        raise LLMError(f"Gemini returned a non-object JSON: {str(parsed)[:200]}")
    return parsed
