"""
Structured JSON calls.

Gemini's `responseSchema` guarantees the model returns JSON matching an exact
shape. `complete_json_with_fallback` uses the provider-agnostic fallback router
for features that must continue on DeepSeek when Gemini is unavailable.

Kept separate from the plain-text `LLMProvider` path because it is Gemini-
specific and schema-driven. Model defaults to the cheap Flash-Lite tier
(config.gemini_blueprint_model), swappable via env with no code change.
"""

from __future__ import annotations

import base64
import json

import httpx

from app.lib.config import get_settings
from app.services.llm import complete_with_fallback
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
        raise LLMError(f"Gemini returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Gemini request failed.") from exc

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError("Gemini returned an unexpected or empty response.") from exc

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("Gemini returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise LLMError("Gemini returned a non-object JSON value.")
    return parsed


def complete_json_with_fallback(
    system_prompt: str, user_prompt: str
) -> tuple[dict, str]:
    """Return a parsed JSON object plus the successful provider name."""
    raw, provider = complete_with_fallback(system_prompt, user_prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"{provider} returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"{provider} returned a non-object JSON value.")
    return parsed, provider


def gemini_json_multimodal(
    system_prompt: str,
    user_prompt: str,
    files: list[tuple[str, bytes]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
) -> dict:
    """
    Multimodal Gemini call: send document/image bytes (PDF, PNG, JPG) inline
    alongside a text instruction, and return the parsed top-level JSON object.

    `files` is a list of (mime_type, raw_bytes). This is what lets quiz
    EXTRACTION read a scanned or typed paper directly with Gemini's vision — no
    OCR needed. Output is forced to JSON via responseMimeType; validate with
    Pydantic afterwards (the question `correct_answer` field is polymorphic, so
    a rigid responseSchema does not fit — same reasoning as `gemini_json`).

    Defaults to the full `gemini_model` (not the cheap Flash-Lite tier) because
    vision extraction accuracy matters. Raises LLMError on any failure.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set — cannot call Gemini.")

    model = model or settings.gemini_model
    url = f"{settings.gemini_base_url}/models/{model}:generateContent"

    parts: list[dict] = [{"text": user_prompt}]
    for mime_type, raw in files:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(raw).decode("ascii"),
                }
            }
        )

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            # Extraction is verbatim parsing, not reasoning — turn OFF Gemini
            # 2.5's default "thinking" so it doesn't waste latency or eat the
            # output budget. This is the single biggest latency win here.
            "thinkingConfig": {"thinkingBudget": 0},
            # Headroom so a long paper's questions aren't truncated mid-JSON.
            "maxOutputTokens": settings.gemini_extraction_max_output_tokens,
        },
    }
    headers = {
        "x-goog-api-key": settings.gemini_api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.gemini_vision_timeout_seconds,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"Gemini returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Gemini request failed.") from exc

    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError("Gemini returned an unexpected or empty response.") from exc

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("Gemini returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise LLMError("Gemini returned a non-object JSON value.")
    return parsed
