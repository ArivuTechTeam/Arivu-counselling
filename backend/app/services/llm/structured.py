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
import time

import httpx

from app.lib.config import get_settings
import app.services.llm as llm_router
from app.services.llm.base import LLMError
from app.services.llm.gemini_http import post_gemini
from app.services.ai_call_logging import ai_provider_attempt, log_ai_call


def gemini_json(
    system_prompt: str,
    user_prompt: str,
    schema: dict | None = None,
    *,
    model: str | None = None,
    temperature: float | None = 0.2,
    max_output_tokens: int | None = None,
    thinking_budget: int | None = None,
    thinking_level: str | None = None,
    allow_model_fallback: bool = True,
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
    generation_config: dict = {"responseMimeType": "application/json"}
    if temperature is not None:
        generation_config["temperature"] = temperature
    if schema is not None:
        generation_config["responseSchema"] = schema
    if max_output_tokens is not None:
        generation_config["maxOutputTokens"] = max_output_tokens
    if thinking_budget is not None:
        generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    if thinking_level is not None:
        if thinking_budget is not None:
            raise ValueError("Use either thinking_budget or thinking_level, not both.")
        generation_config["thinkingConfig"] = {
            "thinkingLevel": thinking_level.upper()
        }
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
        resp = post_gemini(
            settings=settings,
            model=model,
            payload=payload,
            headers=headers,
            timeout=180.0,
            allow_model_fallback=allow_model_fallback,
        )
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
    system_prompt: str,
    user_prompt: str,
    *,
    preferred_provider: str | None = None,
    schema: dict | None = None,
) -> tuple[dict, str]:
    """Return structured JSON, falling back on invalid/empty provider output too.

    Cross-provider fallback used to happen only for HTTP failures. Parsing now
    occurs inside the provider loop so malformed JSON from the primary can safely
    move to the configured fallback. A supplied schema is included in the prompt;
    Pydantic/local validators remain authoritative for polymorphic question data.
    """
    if schema is not None:
        system_prompt = (
            system_prompt
            + "\n\nReturn one JSON object matching this JSON Schema exactly:\n"
            + json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
        )
    failures: list[str] = []
    for index, provider in enumerate(llm_router.get_providers(preferred_provider)):
        try:
            with ai_provider_attempt(was_fallback=index > 0):
                raw = provider.complete(system_prompt, user_prompt)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise LLMError(
                    f"{provider.name} returned a non-object JSON value."
                )
            return parsed, provider.name
        except json.JSONDecodeError:
            failures.append(f"{provider.name} returned invalid JSON")
        except LLMError as exc:
            failures.append(f"{provider.name}: {exc}")
    raise LLMError("All LLM providers failed → " + " | ".join(failures))


def _gemini_json_large(
    system_prompt: str, user_prompt: str, *, model: str, max_output_tokens: int
) -> dict:
    """Text-only Gemini JSON call tuned for LARGE output: 'thinking' disabled so
    the whole budget goes to the answer, and a high output cap so the response
    isn't truncated mid-JSON. Detects the MAX_TOKENS finish reason explicitly."""
    settings = get_settings()
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
            "maxOutputTokens": max_output_tokens,
        },
    }
    headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}
    try:
        resp = post_gemini(
            settings=settings,
            model=model,
            payload=payload,
            headers=headers,
            timeout=getattr(settings, "generation_large_request_timeout_seconds", 600.0),
        )
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"Gemini returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise LLMError("Gemini request failed.") from exc

    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise LLMError("Gemini hit the output-token limit (response truncated).")
    try:
        text = candidate["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise LLMError("Gemini returned an unexpected or empty response.") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("Gemini returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Gemini returned a non-object JSON value.")
    return parsed


def _deepseek_json_large(
    system_prompt: str, user_prompt: str, *, max_tokens: int
) -> dict:
    """DeepSeek JSON call with a raised output cap + truncation detection (its
    default cap silently cuts large JSON, which then fails to parse)."""
    settings = get_settings()
    url = f"{settings.deepseek_base_url}/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "thinking": {
            "type": (
                "enabled"
                if getattr(settings, "deepseek_thinking_enabled", False)
                else "disabled"
            )
        },
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    started_at = time.perf_counter()
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=getattr(settings, "generation_large_request_timeout_seconds", 600.0),
        )
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
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise LLMError("DeepSeek hit the output-token limit (response truncated).")
    try:
        text = choice["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError("DeepSeek returned an unexpected response shape.") from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("DeepSeek returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise LLMError("DeepSeek returned a non-object JSON value.")
    return parsed


def complete_json_large(
    system_prompt: str,
    user_prompt: str,
    *,
    preferred_provider: str | None = None,
) -> tuple[dict, str]:
    """JSON call for LARGE outputs (the Map-Reduce MAP/REDUCE steps).

    Use the requested stage provider first, then the configured fallback. Both
    legs are tuned so a big verbatim JSON response isn't silently truncated,
    and truncation is reported clearly rather than as an opaque parse failure.
    """
    settings = get_settings()
    failures: list[str] = []
    preferred = preferred_provider or "gemini"
    fallback = getattr(settings, "ai_fallback_provider", "gemini")
    order = list(dict.fromkeys([preferred, fallback, "deepseek", "gemini"]))
    for index, provider in enumerate(order):
        try:
            with ai_provider_attempt(was_fallback=index > 0):
                if provider == "deepseek" and settings.deepseek_api_key:
                    return (
                        _deepseek_json_large(
                            system_prompt,
                            user_prompt,
                            max_tokens=settings.deepseek_max_output_tokens,
                        ),
                        "deepseek",
                    )
                if provider == "gemini" and settings.gemini_api_key:
                    return (
                        _gemini_json_large(
                            system_prompt,
                            user_prompt,
                            model=settings.gemini_model,
                            max_output_tokens=settings.generation_map_max_output_tokens,
                        ),
                        "gemini",
                    )
        except LLMError as exc:
            failures.append(f"{provider}: {exc}")
    if not failures:
        raise LLMError(
            "No LLM provider configured — set GEMINI_API_KEY or DEEPSEEK_API_KEY."
        )
    raise LLMError("All LLM providers failed → " + " | ".join(failures))


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
        resp = post_gemini(
            settings=settings,
            model=model,
            payload=payload,
            headers=headers,
            timeout=settings.gemini_vision_timeout_seconds,
        )
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
