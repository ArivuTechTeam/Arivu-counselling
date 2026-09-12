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
from app.lib.api_errors import public_error
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
from app.services.review import RegenerationSourceError, regenerate_question
from app.services.student_access import student_has_graded_question
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


class QuestionEdit(BaseModel):
    question_text: str | None = Field(default=None, min_length=1)
    options: list[dict] | None = None
    correct_answer: Any | None = None
    explanation: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    marks: float | None = Field(default=None, gt=0)


class QuestionOut(BaseModel):
    id: str
    type: str
    question_text: str
    options: list[dict] | None = None
    correct_answer: Any
    explanation: str | None = None
    difficulty: str
    marks: float
    review_status: str


@router.patch("/{question_id}", response_model=QuestionOut)
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


@router.post("/{question_id}/approve", response_model=QuestionOut)
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


@router.post("/{question_id}/reject", response_model=QuestionOut)
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


@router.post("/{question_id}/regenerate", response_model=QuestionOut)
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
    except RegenerationSourceError as exc:
        raise public_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This question cannot be regenerated because its original source "
            "material is unavailable. Edit it manually instead.",
            operation="load regeneration source material",
            exception=exc,
        ) from exc
    except ValueError as exc:
        raise public_error(
            404,
            "Question not found.",
            operation="regenerate question lookup",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't regenerate this question right now. Please try again.",
            operation="regenerate question with AI",
            exception=exc,
        ) from exc


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
    elif not student_has_graded_question(service, question_id, profile):
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
        raise public_error(
            404,
            "Question not found.",
            operation="explain question lookup",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't generate an explanation right now. Please try again.",
            operation="explain question with AI",
            exception=exc,
        ) from exc
