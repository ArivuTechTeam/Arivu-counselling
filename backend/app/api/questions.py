"""
Question review API (Slice 4).

  PATCH /api/v1/questions/{id}            — edit a question's content
  POST  /api/v1/questions/{id}/approve    — mark approved (stamps reviewer)
  POST  /api/v1/questions/{id}/reject     — mark rejected (stamps reviewer)
  POST  /api/v1/questions/{id}/regenerate — AI rewrites the question in place
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.llm import LLMError
from app.services.review import regenerate_question

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _require_staff(profile: CurrentProfile) -> None:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff can review questions.",
        )


class QuestionEdit(BaseModel):
    question_text: str | None = None
    options: list[dict] | None = None
    correct_answer: Any | None = None
    explanation: str | None = None
    difficulty: str | None = None
    marks: float | None = None


@router.patch("/{question_id}")
def edit_question(
    question_id: str,
    body: QuestionEdit,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_staff(profile)
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
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    return updated.data[0]


def _set_review_status(
    question_id: str, profile: CurrentProfile, review_status: str
) -> dict:
    service = get_service_client()
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
    _require_staff(profile)
    return _set_review_status(question_id, profile, "approved")


@router.post("/{question_id}/reject")
def reject_question(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_staff(profile)
    return _set_review_status(question_id, profile, "rejected")


@router.post("/{question_id}/regenerate")
def regenerate(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_staff(profile)
    try:
        return regenerate_question(question_id, profile.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Regeneration failed: {exc}",
        )
