"""Shared Gemini HTTP transport with model-not-found failover."""

from __future__ import annotations

import logging
import threading

import httpx

logger = logging.getLogger(__name__)
_gemini_model_lock = threading.Lock()
_gemini_unavailable_models: set[tuple[str, str]] = set()


def post_gemini(
    *, settings, model: str, payload: dict, headers: dict, timeout: float
) -> httpx.Response:
    """POST to Gemini, retrying a model-specific 404 on the configured fallback.

    Authentication, quota, validation, and network failures are deliberately not
    retried here; those continue through the normal provider fallback path.
    """
    candidates = list(
        dict.fromkeys([model, getattr(settings, "gemini_fallback_model", model)])
    )
    with _gemini_model_lock:
        available_candidates = [
            candidate
            for candidate in candidates
            if (settings.gemini_base_url, candidate) not in _gemini_unavailable_models
        ]
    # Always retain at least the last configured candidate so a temporary 404
    # cannot disable Gemini altogether for the lifetime of the worker.
    candidates = available_candidates or candidates[-1:]
    last_error: httpx.HTTPStatusError | None = None
    for index, candidate in enumerate(candidates):
        url = f"{settings.gemini_base_url}/models/{candidate}:generateContent"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 404 and index + 1 < len(candidates):
                with _gemini_model_lock:
                    _gemini_unavailable_models.add(
                        (settings.gemini_base_url, candidate)
                    )
                logger.warning(
                    "Gemini model %s returned 404; retrying configured fallback %s.",
                    candidate,
                    candidates[index + 1],
                )
                continue
            raise
    assert last_error is not None
    raise last_error
