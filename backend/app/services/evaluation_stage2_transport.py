"""Isolated DeepSeek text transport for direct-score-v2 evaluation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import time
from uuid import uuid4

import httpx

from app.lib.config import get_settings
from app.services.ai_call_logging import log_ai_call
from app.services.evaluation_stage2 import Stage2PermanentError, Stage2RetryableError
from app.services.evaluation_stage2_contract import STAGE2_PROMPT_REVISION

logger = logging.getLogger(__name__)
_RETRYABLE_HTTP = {429, 500, 502, 503}
_ARTIFACT_LIMIT = 512 * 1024


def _with_response(error: Exception) -> Exception:
    setattr(error, "response_received", True)
    return error


@dataclass(frozen=True)
class Stage2Response:
    content: str
    model: str

    def artifact(self, *, sequence: int, route: str) -> dict:
        encoded = self.content.encode("utf-8")
        omitted = len(encoded) > _ARTIFACT_LIMIT
        return {
            "sequence": sequence,
            "route": route,
            "model": self.model,
            "prompt_revision": STAGE2_PROMPT_REVISION,
            "raw_content": "" if omitted else self.content,
            "content_bytes": len(encoded),
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "content_omitted": omitted,
        }


def _acquire_slot(service, holder: str, settings, *, sleep=time.sleep) -> bool:
    """Acquire the fleet lease; database outages fail open, capacity does not."""
    deadline = time.monotonic() + settings.deepseek_slot_wait_seconds
    while True:
        try:
            result = service.rpc("acquire_ai_provider_slot", {
                "p_provider": "deepseek", "p_holder": holder,
                "p_limit": settings.deepseek_max_concurrency, "p_ttl_seconds": 900,
            }).execute()
            if bool(result.data):
                return True
        except Exception as exc:  # semaphore availability must not stop evaluation
            logger.warning("DeepSeek concurrency semaphore unavailable; failing open (%s)", type(exc).__name__)
            return False
        if time.monotonic() >= deadline:
            raise Stage2RetryableError("DeepSeek is at capacity. Evaluation will retry.")
        sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def _release_slot(service, holder: str) -> None:
    try:
        service.rpc("release_ai_provider_slot", {
            "p_provider": "deepseek", "p_holder": holder,
        }).execute()
    except Exception as exc:
        logger.warning("Could not release DeepSeek concurrency lease (%s)", type(exc).__name__)


def deepseek_stage2(
    service, system_prompt: str, payload_json: str, *, post=httpx.post,
    sleep=time.sleep, settings=None, max_tokens: int | None = None,
) -> Stage2Response:
    """Call text mode with retries only when no usable HTTP response was received."""
    settings = settings or get_settings()
    if not settings.deepseek_api_key:
        raise Stage2PermanentError("DEEPSEEK_API_KEY is not configured.")
    completion_limit = max_tokens or settings.deepseek_stage2_max_tokens
    request = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload_json},
        ],
        "temperature": 0,
        "response_format": {"type": "text"},
        "reasoning_effort": settings.deepseek_stage2_thinking_effort,
        "max_tokens": completion_limit,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}
    holder = str(uuid4())
    held = _acquire_slot(service, holder, settings, sleep=sleep)
    try:
        last_error = "request failed"
        for attempt in range(3):
            started = time.perf_counter()
            try:
                response = post(
                    f"{settings.deepseek_base_url}/chat/completions",
                    json=request, headers=headers, timeout=180.0,
                )
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=None, was_fallback=False, started_at=started, error_message=last_error)
                if attempt < 2:
                    sleep(5 * (attempt + 1))
                    continue
                raise Stage2RetryableError("DeepSeek request failed before a response was received.") from exc

            status = response.status_code
            if status >= 400:
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=None, was_fallback=False, started_at=started,
                            error_message=f"HTTP {status}")
                if status in _RETRYABLE_HTTP and attempt < 2:
                    sleep(5 * (attempt + 1))
                    continue
                error = Stage2RetryableError if status in _RETRYABLE_HTTP else Stage2PermanentError
                raise error(f"DeepSeek returned HTTP {status}.")

            # From this point onward an HTTP response exists: never regenerate it.
            try:
                data = response.json()
            except ValueError as exc:
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=None, was_fallback=False, started_at=started,
                            error_message="malformed response envelope")
                raise _with_response(Stage2PermanentError("DeepSeek returned a malformed response envelope.")) from exc
            usage_only = {"usage": data.get("usage") or {}} if isinstance(data, dict) else None
            try:
                choice = data["choices"][0]
                finish = choice.get("finish_reason")
                content = choice["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=usage_only, was_fallback=False, started_at=started,
                            error_message="unexpected response shape")
                raise _with_response(Stage2PermanentError("DeepSeek returned an unexpected response shape.")) from exc
            if finish == "length":
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=usage_only, was_fallback=False, started_at=started,
                            error_message="output truncated at token limit")
                raise _with_response(Stage2PermanentError("DeepSeek Stage 2 output was truncated."))
            if finish not in {"stop", None}:
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=usage_only, was_fallback=False, started_at=started,
                            error_message=f"unexpected finish reason {finish}")
                raise _with_response(Stage2PermanentError(f"DeepSeek ended Stage 2 with finish reason {finish}."))
            if not isinstance(content, str) or not content.strip():
                log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                            response=usage_only, was_fallback=False, started_at=started,
                            error_message="empty Stage 2 content")
                raise _with_response(Stage2PermanentError("DeepSeek returned empty Stage 2 content."))
            log_ai_call(provider="deepseek", model=settings.deepseek_model, request=request,
                        response=usage_only, was_fallback=False, started_at=started)
            return Stage2Response(content=content, model=str(data.get("model") or settings.deepseek_model))
        raise Stage2RetryableError(last_error)
    finally:
        if held:
            _release_slot(service, holder)
