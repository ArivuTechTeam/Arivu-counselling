"""Shared, deterministic timing rules for student quiz attempts.

The overall deadline is the only hard limit.  Per-question values are pacing
guidance, scaled to fit that deadline when an attempt is timed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


NETWORK_GRACE_SECONDS = 10

# These values express relative effort as well as useful defaults for untimed
# practice.  A timed attempt scales them proportionally to its total duration.
QUESTION_PACING_SECONDS = {
    "true_false": 45,
    "mcq_single": 60,
    "fill_blank": 75,
    "mcq_multi": 90,
    "numerical": 120,
}
DEFAULT_PACING_SECONDS = 90


@dataclass(frozen=True)
class DeadlineState:
    deadline_at: str
    remaining_seconds: int
    reached: bool
    beyond_grace: bool


def is_answered(value: Any) -> bool:
    """Return whether an answer has meaningful content."""
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return len(value) > 0
    return True


def _as_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def deadline_state(
    started_at: Any,
    time_limit_minutes: Any,
    *,
    now: datetime | None = None,
) -> DeadlineState | None:
    """Return server-authoritative deadline state, or ``None`` when untimed."""
    started = _as_utc(started_at)
    try:
        minutes = float(time_limit_minutes)
    except (TypeError, ValueError):
        return None
    if started is None or not math.isfinite(minutes) or minutes <= 0:
        return None

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    deadline = started + timedelta(minutes=minutes)
    remaining = max(0, math.ceil((deadline - current).total_seconds()))
    return DeadlineState(
        deadline_at=deadline.isoformat(),
        remaining_seconds=remaining,
        reached=current >= deadline,
        beyond_grace=current > deadline + timedelta(seconds=NETWORK_GRACE_SECONDS),
    )


def pacing_seconds(questions: list[dict], total_seconds: int | None) -> list[int]:
    """Allocate per-question pacing seconds while preserving the exact total."""
    base = [
        QUESTION_PACING_SECONDS.get(q.get("type"), DEFAULT_PACING_SECONDS)
        for q in questions
    ]
    if not base:
        return []
    if total_seconds is None or total_seconds <= 0:
        return base

    scale = total_seconds / sum(base)
    exact = [value * scale for value in base]
    allocated = [math.floor(value) for value in exact]
    remainder = total_seconds - sum(allocated)
    order = sorted(
        range(len(exact)),
        key=lambda index: exact[index] - allocated[index],
        reverse=True,
    )
    for index in order[:remainder]:
        allocated[index] += 1
    return allocated


def effective_time_limit_minutes(
    questions: list[dict], configured_minutes: Any = None
) -> float:
    """Use an explicit positive limit, otherwise derive one from question types."""
    try:
        configured = float(configured_minutes)
    except (TypeError, ValueError):
        configured = 0
    if math.isfinite(configured) and configured > 0:
        return configured
    total_seconds = sum(
        QUESTION_PACING_SECONDS.get(q.get("type"), DEFAULT_PACING_SECONDS)
        for q in questions
    )
    return max(1, math.ceil(total_seconds / 60))


def taking_questions(
    questions: list[dict], time_limit_minutes: Any = None
) -> list[dict]:
    """Add safe pacing guidance to already answer-stripped taking questions."""
    try:
        minutes = float(time_limit_minutes)
        total_seconds = round(minutes * 60) if minutes > 0 else None
    except (TypeError, ValueError):
        total_seconds = None
    budgets = pacing_seconds(questions, total_seconds)
    return [
        {**question, "suggested_seconds": budgets[index]}
        for index, question in enumerate(questions)
    ]


def timing_payload(
    started_at: Any,
    time_limit_minutes: Any,
    *,
    now: datetime | None = None,
) -> dict:
    state = deadline_state(started_at, time_limit_minutes, now=now)
    if state is None:
        return {}
    return {
        "time_limit_minutes": float(time_limit_minutes),
        "started_at": started_at,
        "deadline_at": state.deadline_at,
        "remaining_seconds": state.remaining_seconds,
    }
