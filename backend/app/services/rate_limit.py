"""Atomic, Supabase-backed rate limits for authenticated AI endpoints."""

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


def enforce_ai_rate_limit(
    *,
    profile: CurrentProfile,
    endpoint: str,
    hourly_limit: int,
    action_label: str,
) -> None:
    """Consume one request or raise a friendly 429 response."""
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
        logger.exception("Could not enforce AI rate limit for %s", endpoint)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are temporarily unavailable. Please try again shortly.",
        ) from exc

    data = result.data
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict) or "allowed" not in row:
        logger.error("Malformed AI rate-limit response for %s: %r", endpoint, data)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI features are temporarily unavailable. Please try again shortly.",
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
