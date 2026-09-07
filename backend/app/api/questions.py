"""
Question review API (Slice 4).

  PATCH /api/v1/questions/{id}            — edit a question's content
  POST  /api/v1/questions/{id}/approve    — mark approved (stamps reviewer)
  POST  /api/v1/questions/{id}/reject     — mark rejected (stamps reviewer)
  POST  /api/v1/questions/{id}/regenerate — AI rewrites the question in place
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.events import (
    QUESTION_APPROVED,
    QUESTION_EDITED,
    QUESTION_REGENERATED,
    QUESTION_REJECTED,
    log_event,
)
from app.services.llm import LLMError
from app.services.rate_limit import (
    QUESTION_EXPLAIN,
    QUESTION_REGENERATE,
    enforce_ai_rate_limit,
)
from app.services.review import regenerate_question
from app.services.tutor import explain_question

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])

def _require_teacher(profile: CurrentProfile) -> None:
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can review questions.",
        )


def _assert_teacher_question(
    service, question_id: str, profile: CurrentProfile
) -> None:
    question = (
        service.table("questions")
        .select("id")
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if question is None or not question.data:
        raise HTTPException(status_code=404, detail="Question not found.")


def _student_has_graded_question(
    service, question_id: str, profile: CurrentProfile
) -> bool:
    attempt_answers = (
        service.table("attempt_answers")
        .select("attempt_id")
        .eq("question_id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    attempt_ids = [row["attempt_id"] for row in attempt_answers]
    if attempt_ids:
        attempts = (
            service.table("quiz_attempts")
            .select("id")
            .in_("id", attempt_ids)
            .eq("tenant_id", profile.tenant_id)
            .eq("student_id", profile.user_id)
            .eq("status", "graded")
            .limit(1)
            .execute()
            .data
            or []
        )
        if attempts:
            return True

    practice_answers = (
        service.table("practice_answers")
        .select("session_id")
        .eq("question_id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    session_ids = [row["session_id"] for row in practice_answers]
    if not session_ids:
        return False
    sessions = (
        service.table("practice_sessions")
        .select("id")
        .in_("id", session_ids)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("status", "graded")
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(sessions)


class QuestionEdit(BaseModel):
    question_text: str | None = Field(default=None, min_length=1)
    options: list[dict] | None = None
    correct_answer: Any | None = None
    explanation: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    marks: float | None = Field(default=None, gt=0)


@router.patch("/{question_id}")
def edit_question(
    question_id: str,
    body: QuestionEdit,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)
    # Only update the fields the teacher actually sent.
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )
    service = get_service_client()
    updated = (
        service.table("questions")
        .update(updates)
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)  # tenant guard
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    # Instrument: which fields the teacher changed (powers "approved without
    # edits" and "what do teachers fix most").
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_EDITED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
        metadata={"edited_fields": list(updates.keys())},
    )
    return updated.data[0]


def _set_review_status(
    question_id: str, profile: CurrentProfile, review_status: str
) -> dict:
    service = get_service_client()
    _assert_teacher_question(service, question_id, profile)
    updated = (
        service.table("questions")
        .update(
            {
                "review_status": review_status,
                "reviewed_by": profile.user_id,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    return updated.data[0]


@router.post("/{question_id}/approve")
def approve_question(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)
    result = _set_review_status(question_id, profile, "approved")
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_APPROVED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
    )
    return result


@router.post("/{question_id}/reject")
def reject_question(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)
    result = _set_review_status(question_id, profile, "rejected")
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_REJECTED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
    )
    return result


@router.post("/{question_id}/regenerate")
def regenerate(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)
    service = get_service_client()
    _assert_teacher_question(service, question_id, profile)
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUESTION_REGENERATE,
        hourly_limit=get_settings().rate_limit_question_regenerate_per_hour,
        action_label="question regeneration",
    )
    try:
        result = regenerate_question(question_id, profile.tenant_id)
        log_event(
            tenant_id=profile.tenant_id,
            event_type=QUESTION_REGENERATED,
            actor_id=profile.user_id,
            actor_role=profile.role,
            subject_type="question",
            subject_id=question_id,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Regeneration failed: {exc}",
        )


@router.post("/{question_id}/explain")
def explain(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    AI Tutor: a deeper step-by-step explanation + a simplified version + hints,
    cached per question in ai_explanations. Teachers may explain their own
    questions; students gain access only after the question has been graded.
    """
    if profile.role not in {"teacher", "student"}:
        raise HTTPException(status_code=403, detail="Teachers and students only.")
    service = get_service_client()
    if profile.role == "teacher":
        _assert_teacher_question(service, question_id, profile)
    elif not _student_has_graded_question(service, question_id, profile):
        raise HTTPException(
            status_code=403,
            detail="Explanations are available after you submit this question.",
        )
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUESTION_EXPLAIN,
        hourly_limit=get_settings().rate_limit_question_explain_per_hour,
        action_label="question explanations",
    )
    try:
        return explain_question(question_id, profile.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Explanation failed: {exc}",
        )
