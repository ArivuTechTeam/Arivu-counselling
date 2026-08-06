"""
Quiz generation API (Slice 3).

POST /api/v1/quiz-sets/generate
  Body: which document, how many questions, which types, cognitive level,
  difficulty. Runs the generation pipeline and returns the created questions
  (status pending_review — the teacher approves/edits them in Slice 4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.generation import generate_quiz
from app.services.llm import LLMError
from app.services.review import get_quiz_set_detail

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["quiz"])

CORE_TYPES = {"mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"}
STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


class GenerateRequest(BaseModel):
    document_id: str
    num_questions: int = Field(ge=1, le=30)
    question_types: list[str]
    cognitive_level: Literal["theory", "practical", "mixed"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    # Which subject this quiz belongs to. Enrolled students see quizzes for the
    # subjects in their course. Optional: if omitted, no students are targeted.
    subject_id: str | None = None


@router.post("/generate")
def generate(
    req: GenerateRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff can generate quizzes.",
        )

    invalid = set(req.question_types) - CORE_TYPES
    if not req.question_types or invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported question types: {sorted(invalid) or 'none selected'}.",
        )

    try:
        return generate_quiz(
            document_id=req.document_id,
            num_questions=req.num_questions,
            question_types=req.question_types,
            cognitive_level=req.cognitive_level,
            difficulty=req.difficulty,
            subject_id=req.subject_id,
            profile=profile,
        )
    except ValueError as exc:
        # Bad input (document missing, no extractable text).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except LLMError as exc:
        # The model call or its output failed.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Quiz generation failed: {exc}",
        )


def _require_staff(profile: CurrentProfile) -> None:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff can access quiz sets.",
        )


@router.get("")
def list_quiz_sets(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """List the tenant's quiz sets, newest first."""
    _require_staff(profile)
    service = get_service_client()
    rows = (
        service.table("quiz_sets")
        .select("id, title, status, created_at, published_at")
        .eq("tenant_id", profile.tenant_id)
        .order("created_at", desc=True)
        .execute()
    )
    return rows.data or []


@router.get("/{quiz_set_id}")
def get_quiz_set(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Full quiz set with its variant(s) and each variant's ordered questions."""
    _require_staff(profile)
    try:
        return get_quiz_set_detail(quiz_set_id, profile.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{quiz_set_id}/publish")
def publish_quiz_set(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Publish the set. Students only ever see questions with review_status
    'approved' inside a published set (enforced by RLS), so pending/rejected
    questions simply don't appear.
    """
    _require_staff(profile)
    service = get_service_client()
    updated = (
        service.table("quiz_sets")
        .update(
            {
                "status": "published",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    return updated.data[0]
