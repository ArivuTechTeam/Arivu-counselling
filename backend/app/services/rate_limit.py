"""Atomic, Supabase-backed rate limits for authenticated endpoints."""

from __future__ import annotations

import logging
import math

from fastapi import HTTPException, status

from app.lib.auth import CurrentProfile
from app.lib.supabase import get_service_client

logger = logging.getLogger(__name__)

QUIZ_GENERATION = "quiz_generation"
BLUEPRINT_GENERATION = "blueprint_generation"
TOPIC_EXTRACTION = "topic_extraction"
QUESTION_REGENERATE = "question_regenerate"
QUESTION_EXPLAIN = "question_explain"
QUIZ_EXTRACTION = "quiz_extraction"
CHALLENGE_JOIN = "challenge_join"
DESCRIPTIVE_GRADING = "descriptive_grading"
PAPER_GENERATION = "paper_generation"
HANDWRITTEN_EVALUATION = "handwritten_evaluation"


def enforce_rate_limit(
    *,
    profile: CurrentProfile,
    endpoint: str,
    hourly_limit: int,
    action_label: str,
    unavailable_detail: str = (
        "This feature is temporarily unavailable. Please try again shortly."
    ),
) -> None:
    """Consume one request from the shared rolling-hour limiter."""
    try:
        result = get_service_client().rpc(
            "consume_ai_rate_limit",
            {
                "p_tenant_id": profile.tenant_id,
                "p_user_id": profile.user_id,
                "p_endpoint": endpoint,
                "p_limit": hourly_limit,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - fail closed if quota state is unknown
        logger.error(
            "Could not enforce rate limit for %s (%s)",
            endpoint,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        ) from exc

    data = result.data
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict) or "allowed" not in row:
        # Never log an upstream response body: provider/database payloads can
        # contain user data or credentials in an error envelope.
        logger.error(
            "Malformed rate-limit response for %s (response_type=%s)",
            endpoint,
            type(data).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )

    if row["allowed"]:
        return

    retry_seconds = max(1, int(row.get("retry_after_seconds") or 1))
    retry_minutes = max(1, math.ceil(retry_seconds / 60))
    minute_word = "minute" if retry_minutes == 1 else "minutes"
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"You've reached the hourly limit for {action_label}. "
            f"Please try again in {retry_minutes} {minute_word}."
        ),
        headers={"Retry-After": str(retry_seconds)},
    )


def enforce_ai_rate_limit(
    *,
    profile: CurrentProfile,
    endpoint: str,
    hourly_limit: int,
    action_label: str,
) -> None:
    """Consume one request or raise a friendly 429 response."""
    enforce_rate_limit(
        profile=profile,
        endpoint=endpoint,
        hourly_limit=hourly_limit,
        action_label=action_label,
        unavailable_detail=(
            "AI features are temporarily unavailable. Please try again shortly."
        ),
    )
