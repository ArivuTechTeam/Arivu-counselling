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
import logging
import time
from urllib.parse import urlsplit

import httpx

from app.lib.config import get_settings
import app.services.llm as llm_router
from app.services.llm.base import LLMError
from app.services.llm.gemini_http import post_gemini
from app.services.ai_call_logging import ai_provider_attempt, log_ai_call


logger = logging.getLogger(__name__)

# Match ExamApp's proven native-document transport boundary. These values count
# base64 characters rather than decoded bytes so the request retains room for
# prompts, schemas, and JSON framing. A file above the per-file threshold is
# uploaded unchanged to Gemini Files API; cumulative inline evidence must never
# exceed the second limit.
GEMINI_FILES_API_THRESHOLD_B64 = 10_000_000
GEMINI_INLINE_B64_LIMIT = 18_000_000
GEMINI_FILE_READY_TIMEOUT_SECONDS = 120.0
GEMINI_FILE_READY_POLL_SECONDS = 1.5


def _requires_gemini_files_api(encoded_size: int, inline_b64_total: int) -> bool:
    return (
        encoded_size > GEMINI_FILES_API_THRESHOLD_B64
        or inline_b64_total + encoded_size > GEMINI_INLINE_B64_LIMIT
    )


def _gemini_api_origin(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise LLMError("GEMINI_BASE_URL is invalid.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _gemini_file_state(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("name")
    return str(value or "").strip().upper()


def _wait_for_gemini_file_active(
    *, file_uri: str, api_key: str, base_url: str, initial_state: object = None,
    timeout_seconds: float = GEMINI_FILE_READY_TIMEOUT_SECONDS,
    poll_seconds: float = GEMINI_FILE_READY_POLL_SECONDS,
) -> bool:
    """Wait until Gemini has finished processing an uploaded native file."""
    state = _gemini_file_state(initial_state)
    if state == "ACTIVE":
        return True
    if state in {"FAILED", "ERROR", "CANCELLED"}:
        return False

    status_url = str(file_uri or "").strip()
    if not status_url:
        return False
    if not status_url.startswith(("http://", "https://")):
        status_url = f"{base_url.rstrip('/')}/{status_url.lstrip('/')}"

    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                status_url,
                headers={"x-goog-api-key": api_key},
                timeout=30.0,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Gemini Files API readiness check failed (%s)", type(exc).__name__
            )
            return False
        file_info = body.get("file", body) if isinstance(body, dict) else {}
        state = _gemini_file_state((file_info or {}).get("state"))
        if state == "ACTIVE":
            return True
        if state in {"FAILED", "ERROR", "CANCELLED"}:
            return False
        time.sleep(max(poll_seconds, 0.0))
    logger.warning("Gemini Files API upload did not become active before timeout")
    return False


def _upload_to_gemini_files_api(
    *, raw: bytes, mime_type: str, display_name: str, api_key: str,
    base_url: str,
) -> str:
    """Upload one unchanged document and return its active Gemini file URI."""
    upload_url = f"{_gemini_api_origin(base_url)}/upload/v1beta/files"
    try:
        initialized = httpx.post(
            upload_url,
            json={"file": {"display_name": display_name}},
            headers={
                "x-goog-api-key": api_key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(raw)),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        initialized.raise_for_status()
        resumable_url = initialized.headers.get("X-Goog-Upload-URL")
        if not resumable_url:
            raise LLMError("Gemini Files API did not return an upload URL.")

        uploaded = httpx.post(
            resumable_url,
            content=raw,
            headers={
                "Content-Length": str(len(raw)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            timeout=300.0,
        )
        uploaded.raise_for_status()
        body = uploaded.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMError("Gemini Files API upload failed.") from exc

    file_info = body.get("file", {}) if isinstance(body, dict) else {}
    file_uri = str(file_info.get("uri") or "").strip()
    if not file_uri:
        raise LLMError("Gemini Files API did not return a file URI.")
    if not _wait_for_gemini_file_active(
        file_uri=file_uri,
        api_key=api_key,
        base_url=base_url,
        initial_state=file_info.get("state"),
    ):
        raise LLMError("Gemini Files API upload did not become active.")
    logger.info(
        "Gemini Files API upload active (mime=%s, bytes=%d)", mime_type, len(raw)
    )
    return file_uri


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
    system_prompt: str, user_prompt: str, *, model: str, max_output_tokens: int,
    schema: dict | None = None, temperature: float = 0.2,
) -> dict:
    """Text-only Gemini JSON call tuned for LARGE output: 'thinking' disabled so
    the whole budget goes to the answer, and a high output cap so the response
    isn't truncated mid-JSON. Detects the MAX_TOKENS finish reason explicitly."""
    settings = get_settings()
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
            "maxOutputTokens": max_output_tokens,
        },
    }
    if schema is not None:
        payload["generationConfig"]["responseSchema"] = schema
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
    system_prompt: str, user_prompt: str, *, max_tokens: int,
    temperature: float = 0.2,
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
        "temperature": temperature,
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
    schema: dict | None = None,
    temperature: float = 0.2,
) -> tuple[dict, str]:
    """JSON call for LARGE outputs (the Map-Reduce MAP/REDUCE steps).

    Use the requested stage provider first, then the configured fallback. Both
    legs are tuned so a big verbatim JSON response isn't silently truncated,
    and truncation is reported clearly rather than as an opaque parse failure.
    """
    settings = get_settings()
    if schema is not None:
        system_prompt = (
            system_prompt
            + "\n\nReturn one JSON object matching this JSON Schema exactly:\n"
            + json.dumps(schema, separators=(",", ":"), ensure_ascii=False)
        )
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
                            temperature=temperature,
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
                            schema=schema,
                            temperature=temperature,
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
    schema: dict | None = None,
    max_output_tokens: int | None = None,
    thinking_budget: int | None = None,
    allow_model_fallback: bool = True,
) -> dict:
    """
    Multimodal Gemini call using inline bytes for small evidence and Gemini's
    Files API for larger documents, then return the parsed JSON object.

    `files` is a list of (mime_type, raw_bytes). This is what lets quiz
    EXTRACTION read a scanned or typed paper directly with Gemini's vision — no
    OCR needed. Output is forced to JSON via responseMimeType. Callers with a
    fixed contract may pass `schema`; legacy polymorphic extraction callers omit
    it and retain their existing validation path.

    Defaults to the full `gemini_model` (not the cheap Flash-Lite tier) because
    vision extraction accuracy matters. Raises LLMError on any failure.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set — cannot call Gemini.")

    model = model or settings.gemini_model

    parts: list[dict] = [{"text": user_prompt}]
    inline_b64_total = 0
    for index, (mime_type, raw) in enumerate(files):
        encoded = base64.b64encode(raw).decode("ascii")
        needs_files_api = _requires_gemini_files_api(
            len(encoded), inline_b64_total
        )
        if needs_files_api:
            try:
                file_uri = _upload_to_gemini_files_api(
                    raw=raw,
                    mime_type=mime_type,
                    display_name=f"evaluation_document_{index}",
                    api_key=settings.gemini_api_key,
                    base_url=settings.gemini_base_url,
                )
            except LLMError as exc:
                # Falling back is safe only if the complete evidence still fits.
                # Never drop a required document merely to let extraction run.
                if inline_b64_total + len(encoded) > GEMINI_INLINE_B64_LIMIT:
                    raise LLMError(
                        "Gemini Files API failed and the complete document is too "
                        "large for the safe inline request budget."
                    ) from exc
                logger.warning(
                    "Gemini Files API failed; using complete evidence inline "
                    "within the safe request budget"
                )
                parts.append({
                    "inline_data": {"mime_type": mime_type, "data": encoded}
                })
                inline_b64_total += len(encoded)
            else:
                parts.append({
                    "file_data": {"mime_type": mime_type, "file_uri": file_uri}
                })
        else:
            parts.append({
                "inline_data": {"mime_type": mime_type, "data": encoded}
            })
            inline_b64_total += len(encoded)

    generation_config = {
        "temperature": temperature,
        "responseMimeType": "application/json",
        "thinkingConfig": {
            "thinkingBudget": 0 if thinking_budget is None else thinking_budget
        },
        "maxOutputTokens": (
            settings.gemini_extraction_max_output_tokens
            if max_output_tokens is None else max_output_tokens
        ),
    }
    if schema is not None:
        generation_config["responseSchema"] = schema
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
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
            timeout=settings.gemini_vision_timeout_seconds,
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
