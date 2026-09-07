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
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.blueprint import generate_blueprint_quiz
from app.services.generation import generate_quiz
from app.services.llm import LLMError
from app.services.rate_limit import (
    BLUEPRINT_GENERATION,
    QUIZ_GENERATION,
    enforce_ai_rate_limit,
)
from app.services.review import get_quiz_set_detail

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["quiz"])

CORE_TYPES = {"mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"}


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
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can generate quizzes.",
        )

    invalid = set(req.question_types) - CORE_TYPES
    if not req.question_types or invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported question types: {sorted(invalid) or 'none selected'}.",
        )

    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUIZ_GENERATION,
        hourly_limit=get_settings().rate_limit_quiz_generation_per_hour,
        action_label="quiz generation",
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


class BlueprintTopicIn(BaseModel):
    name: str
    weight: Literal["high", "medium", "low"]


class BlueprintGenerateRequest(BaseModel):
    document_id: str
    subject_id: str
    chapter_name: str
    selected_topics: list[BlueprintTopicIn] = []
    # How many questions of EACH type the teacher wants, e.g.
    # {"mcq_single": 3, "true_false": 2, "fill_blank": 5}. The total is the sum;
    # only types with a positive count are generated.
    type_counts: dict[str, int]
    cognitive_level: Literal["theory", "practical", "mixed"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


@router.post("/generate-blueprint")
def generate_blueprint(
    req: BlueprintGenerateRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Blueprint-driven generation (Slice 7): whole-document coverage weighted
    toward the teacher's selected High/Med/Low topics. Stores chapter + topics
    and tags questions to topics, then hands off to the normal review flow.
    """
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can generate quizzes.",
        )
    if not req.chapter_name.strip():
        raise HTTPException(status_code=400, detail="Chapter name is required.")

    # Keep only positive counts; validate the types and the overall total.
    type_counts = {t: n for t, n in req.type_counts.items() if n and n > 0}
    invalid = set(type_counts) - CORE_TYPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported question types: {sorted(invalid)}.",
        )
    total = sum(type_counts.values())
    if total < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a question count of at least 1 for one or more types.",
        )
    if total > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That's more than 50 questions in total — please reduce the counts.",
        )

    enforce_ai_rate_limit(
        profile=profile,
        endpoint=BLUEPRINT_GENERATION,
        hourly_limit=get_settings().rate_limit_blueprint_per_hour,
        action_label="blueprint generation",
    )
    try:
        return generate_blueprint_quiz(
            document_id=req.document_id,
            subject_id=req.subject_id,
            chapter_name=req.chapter_name,
            selected_topics=[t.model_dump() for t in req.selected_topics],
            total_questions=total,
            question_types=list(type_counts.keys()),
            type_counts=type_counts,
            cognitive_level=req.cognitive_level,
            difficulty=req.difficulty,
            profile=profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Quiz generation failed: {exc}",
        )


def _require_teacher(profile: CurrentProfile) -> None:
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can access quiz sets.",
        )


def _teacher_quiz_set(service, quiz_set_id: str, profile: CurrentProfile) -> dict:
    result = (
        service.table("quiz_sets")
        .select("id")
        .eq("id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    return result.data


@router.get("")
def list_quiz_sets(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """List the tenant's quiz sets, newest first."""
    _require_teacher(profile)
    service = get_service_client()
    rows = (
        service.table("quiz_sets")
        .select("id, title, status, created_at, published_at")
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
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
    _require_teacher(profile)
    service = get_service_client()
    _teacher_quiz_set(service, quiz_set_id, profile)
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
    _require_teacher(profile)
    service = get_service_client()
    _teacher_quiz_set(service, quiz_set_id, profile)
    variants = (
        service.table("quiz_variants")
        .select("id")
        .eq("quiz_set_id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    variant_ids = [row["id"] for row in variants]
    links = []
    if variant_ids:
        links = (
            service.table("quiz_variant_questions")
            .select("question_id")
            .in_("variant_id", variant_ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        )
    question_ids = [row["question_id"] for row in links]
    approved = []
    if question_ids:
        approved = (
            service.table("questions")
            .select("id")
            .in_("id", question_ids)
            .eq("tenant_id", profile.tenant_id)
            .eq("created_by", profile.user_id)
            .eq("review_status", "approved")
            .limit(1)
            .execute()
            .data
            or []
        )
    if not approved:
        raise HTTPException(
            status_code=400,
            detail="Approve at least one question before publishing.",
        )
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
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    return updated.data[0]


@router.post("/{quiz_set_id}/approve-all")
def approve_all_questions(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Bulk-approve every still-'pending_review' question in the set. Questions the
    teacher explicitly rejected stay rejected. Lets a teacher accept a good batch
    in one click instead of approving 20 questions individually.
    """
    _require_teacher(profile)
    service = get_service_client()
    _teacher_quiz_set(service, quiz_set_id, profile)

    variants = (
        service.table("quiz_variants")
        .select("id")
        .eq("quiz_set_id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    variant_ids = [v["id"] for v in variants]
    if not variant_ids:
        raise HTTPException(status_code=404, detail="Quiz set not found.")

    links = (
        service.table("quiz_variant_questions")
        .select("question_id")
        .in_("variant_id", variant_ids)
        .execute()
        .data
        or []
    )
    question_ids = list({link["question_id"] for link in links})
    if not question_ids:
        return {"approved": 0}

    updated = (
        service.table("questions")
        .update(
            {
                "review_status": "approved",
                "reviewed_by": profile.user_id,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .in_("id", question_ids)
        .eq("review_status", "pending_review")
        .eq("tenant_id", profile.tenant_id)
        .execute()
    )
    return {"approved": len(updated.data or [])}
