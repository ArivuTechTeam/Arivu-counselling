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
from app.lib.api_errors import public_error
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.blueprint import generate_blueprint_quiz
from app.services.events import QUIZ_PUBLISHED, log_event
from app.services.extraction import extract_text
from app.services.generation import generate_quiz
from app.services.generation_jobs import create_generation_job, launch_job
from app.services.llm import LLMError
from app.services.quiz_generator_service import QuizGeneratorService
from app.services.rate_limit import (
    BLUEPRINT_GENERATION,
    QUIZ_GENERATION,
    TOPIC_EXTRACTION,
    enforce_ai_rate_limit,
)
from app.services.review import get_quiz_set_detail
from app.services.topics import extract_topics

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
        raise public_error(
            status.HTTP_400_BAD_REQUEST,
            "The selected document or subject could not be used to generate this quiz.",
            operation="prepare quiz generation",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't generate the quiz right now. Please try again.",
            operation="generate quiz with AI",
            exception=exc,
        ) from exc


class BlueprintTopicIn(BaseModel):
    name: str
    weight: Literal["high", "medium", "low"] = "medium"
    # Per-topic blueprint: exact per-format counts for THIS topic, e.g.
    # {"mcq_single": 2, "fill_blank": 1}. When any selected topic sends `counts`,
    # the whole request is treated as per-topic mode (the weight is ignored and
    # the quiz is built only from the selected topics).
    counts: dict[str, int] | None = None


class BlueprintGenerateRequest(BaseModel):
    document_id: str
    subject_id: str
    chapter_name: str
    selected_topics: list[BlueprintTopicIn] = Field(default_factory=list)
    # Legacy mode: how many questions of EACH type across the whole quiz, e.g.
    # {"mcq_single": 3, "true_false": 2}. Optional — omitted in per-topic mode,
    # where each topic carries its own counts and the total is their sum.
    type_counts: dict[str, int] = Field(default_factory=dict)
    cognitive_level: Literal["theory", "practical", "mixed"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


def _resolve_blueprint_plan(
    selected_topics: list[BlueprintTopicIn], type_counts: dict[str, int]
) -> tuple[list[dict], dict[str, int], int, list[str]]:
    """Resolve a blueprint request into (selected dicts, aggregate type_counts,
    total, question_types), validating the question types.

    Per-topic mode — any selected topic carries its own `counts`: the plan is the
    sum of every topic's per-format counts, the topic dicts carry those counts
    through to the generator, and the aggregate drives the exact-mix enforcement.
    Legacy mode — no per-topic counts: the global `type_counts` drive the total.
    """
    normalized_names: set[str] = set()
    for topic in selected_topics:
        name = topic.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Every selected topic needs a name.",
            )
        normalized = name.casefold()
        if normalized in normalized_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Select each topic only once (‘{name}’ is duplicated).",
            )
        normalized_names.add(normalized)

    per_topic = any(t.counts is not None for t in selected_topics)
    if per_topic:
        selected: list[dict] = []
        aggregate: dict[str, int] = {}
        for topic in selected_topics:
            raw_counts = topic.counts or {}
            invalid = set(raw_counts) - CORE_TYPES
            if invalid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported question types: {sorted(invalid)}.",
                )
            negative = sorted(kind for kind, count in raw_counts.items() if count < 0)
            if negative:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Question counts cannot be negative: {negative}.",
                )
            counts = {k: int(v) for k, v in raw_counts.items() if v > 0}
            if sum(counts.values()) < 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Every selected topic needs at least one question (‘{topic.name}’).",
                )
            selected.append({"name": topic.name.strip(), "counts": counts})
            for kind, count in counts.items():
                aggregate[kind] = aggregate.get(kind, 0) + count
        total = sum(aggregate.values())
        return selected, aggregate, total, list(aggregate.keys())

    counts = {t: n for t, n in type_counts.items() if n and n > 0}
    invalid = set(counts) - CORE_TYPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported question types: {sorted(invalid)}.",
        )
    total = sum(counts.values())
    selected = [
        {**topic.model_dump(), "name": topic.name.strip()} for topic in selected_topics
    ]
    return selected, counts, total, list(counts.keys())


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

    selected, type_counts, total, question_types = _resolve_blueprint_plan(
        req.selected_topics, req.type_counts
    )
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
    if len(req.selected_topics) > total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Select no more topics than the total number of requested questions."
            ),
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
            selected_topics=selected,
            total_questions=total,
            question_types=question_types,
            type_counts=type_counts,
            cognitive_level=req.cognitive_level,
            difficulty=req.difficulty,
            profile=profile,
        )
    except ValueError as exc:
        raise public_error(
            status.HTTP_400_BAD_REQUEST,
            "The selected document, subject, or blueprint could not be used.",
            operation="prepare blueprint generation",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't generate the blueprint quiz right now. Please try again.",
            operation="generate blueprint quiz with AI",
            exception=exc,
        ) from exc


def _require_teacher(profile: CurrentProfile) -> None:
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can access quiz sets.",
        )


# --- Large-document (chunked Map-Reduce) generation -------------------------
# Small documents (<= trigger) keep the existing single-pass topic extraction,
# untouched. Large ones are analysed in the background (chunk -> MAP -> REDUCE)
# and the teacher picks topics from the resulting Master Blueprint.


class AnalyzeRequest(BaseModel):
    document_id: str


def _owned_document(service, document_id: str, profile: CurrentProfile) -> dict:
    doc = (
        service.table("documents")
        .select("storage_path, file_type")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc.data


@router.post("/analyze")
def analyze_document(
    req: AnalyzeRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Route a document by size. Small documents return their topics directly
    (unchanged behaviour); large ones kick off a background analysis job and
    return its id for the client to poll."""
    if profile.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can analyze documents.")

    service = get_service_client()
    doc = _owned_document(service, req.document_id, profile)

    text = extract_text(download_bytes(doc["storage_path"]), doc["file_type"])
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="This document has no extractable text (scanned image PDF?).",
        )

    # Large document → background Map-Reduce analysis job.
    if len(text) > get_settings().chunking_trigger_chars:
        # Reserve the profile call before returning a job id. This makes repeated
        # Analyze clicks fail immediately with 429, while the remaining MAP and
        # REDUCE calls consume the same atomic limit inside the worker.
        enforce_ai_rate_limit(
            profile=profile,
            endpoint=TOPIC_EXTRACTION,
            hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
            action_label="large-document analysis",
        )
        job_id = create_generation_job(
            document_id=req.document_id,
            tenant_id=profile.tenant_id,
            created_by=profile.user_id,
            params={"profile_rate_limit_reserved": True},
        )
        return {"mode": "job", "document_id": req.document_id, "job_id": job_id, "status": "queued"}

    # Small document → existing single-pass topic extraction.
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=TOPIC_EXTRACTION,
        hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
        action_label="topic extraction",
    )
    try:
        topics = extract_topics(text)
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't extract topics right now. Please try again.",
            operation="extract document topics with AI",
            exception=exc,
        ) from exc
    return {"mode": "direct", "document_id": req.document_id, "topics": topics}


def _owned_job(service, job_id: str, profile: CurrentProfile) -> dict:
    res = (
        service.table("quiz_generation_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if res is None or not res.data:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return res.data


def _fail_if_stuck(service, job: dict, profile: CurrentProfile) -> dict:
    """Turn an abandoned in-process worker into a retryable failed job."""
    if job.get("status") != "running" or not job.get("updated_at"):
        return job
    try:
        updated_at = datetime.fromisoformat(str(job["updated_at"]).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return job
    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds <= get_settings().generation_chunk_stuck_seconds:
        return job

    message = "Analysis stopped before it finished. Retry to continue saved sections."
    now = datetime.now(timezone.utc).isoformat()
    (
        service.table("document_chunks")
        .update({"map_status": "failed", "error_message": message, "updated_at": now})
        .eq("document_id", job["document_id"])
        .eq("tenant_id", profile.tenant_id)
        .eq("map_status", "running")
        .execute()
    )
    (
        service.table("quiz_generation_jobs")
        .update(
            {
                "status": "failed",
                "phase": "failed",
                "error_message": message,
                "updated_at": now,
            }
        )
        .eq("id", job["id"])
        .eq("tenant_id", profile.tenant_id)
        .eq("status", "running")
        .execute()
    )
    return {**job, "status": "failed", "phase": "failed", "error_message": message}


@router.get("/generation-jobs/{job_id}")
def get_generation_job(
    job_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Poll a large-document analysis job. When ready, includes the Master
    Blueprint's topics for the teacher to select."""
    _require_teacher(profile)
    service = get_service_client()
    job = _owned_job(service, job_id, profile)
    job = _fail_if_stuck(service, job, profile)

    blueprint = job.get("master_blueprint") or {}
    topics = [
        {
            "name": t.get("topic_name"),
            "subtopics": t.get("subtopics") or [],
            "page_ranges": t.get("source_page_ranges") or [],
        }
        for t in (blueprint.get("topics") or [])
        if t.get("topic_name")
    ]
    return {
        "job_id": job["id"],
        "status": job["status"],
        "phase": job["phase"],
        "total_chunks": job.get("total_chunks", 0),
        "done_chunks": job.get("done_chunks", 0),
        "error_message": job.get("error_message"),
        "topics": topics,
        "quiz_set_id": job.get("quiz_set_id"),
    }


@router.post("/generation-jobs/{job_id}/retry")
def retry_generation_job(
    job_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Resume a failed/partial analysis job. Idempotent: already-done chunks are
    skipped, so this fills the gaps rather than restarting from scratch."""
    _require_teacher(profile)
    service = get_service_client()
    job = _owned_job(service, job_id, profile)
    if job["status"] not in ("failed", "partial"):
        raise HTTPException(
            status_code=400,
            detail="Only a failed or partial analysis can be retried.",
        )
    service.table("quiz_generation_jobs").update(
        {"status": "queued", "phase": "queued", "error_message": None}
    ).eq("id", job_id).eq("tenant_id", profile.tenant_id).execute()
    launch_job(job_id)
    return {"job_id": job_id, "status": "queued"}


class JobGenerateRequest(BaseModel):
    subject_id: str
    chapter_name: str
    selected_topics: list[BlueprintTopicIn] = Field(default_factory=list)
    # Optional in per-topic mode (see BlueprintGenerateRequest.type_counts).
    type_counts: dict[str, int] = Field(default_factory=dict)
    cognitive_level: Literal["theory", "practical", "mixed"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


@router.post("/generation-jobs/{job_id}/generate")
def generate_from_job(
    job_id: str,
    req: JobGenerateRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Generate the quiz from a ready job's Master Blueprint (single AI call),
    then hand off to the normal review flow — same as small-doc generation."""
    if profile.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can generate quizzes.")
    if not req.chapter_name.strip():
        raise HTTPException(status_code=400, detail="Chapter name is required.")

    selected, type_counts, total, question_types = _resolve_blueprint_plan(
        req.selected_topics, req.type_counts
    )
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
    if len(req.selected_topics) > total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Select no more topics than the total number of requested questions."
            ),
        )

    enforce_ai_rate_limit(
        profile=profile,
        endpoint=BLUEPRINT_GENERATION,
        hourly_limit=get_settings().rate_limit_blueprint_per_hour,
        action_label="blueprint generation",
    )
    try:
        return QuizGeneratorService().generate_from_job(
            job_id=job_id,
            subject_id=req.subject_id,
            chapter_name=req.chapter_name,
            selected_topics=selected,
            total_questions=total,
            question_types=question_types,
            type_counts=type_counts,
            cognitive_level=req.cognitive_level,
            difficulty=req.difficulty,
            profile=profile,
        )
    except ValueError as exc:
        raise public_error(
            status.HTTP_400_BAD_REQUEST,
            "The analysis job, subject, or blueprint could not be used.",
            operation="prepare blueprint generation from job",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't generate the quiz right now. Please try again.",
            operation="generate quiz from blueprint with AI",
            exception=exc,
        ) from exc


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
    return [row for row in (rows.data or []) if row.get("status") != "archived"]


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
        raise public_error(
            404,
            "Quiz set not found.",
            operation="load quiz set detail",
            exception=exc,
        ) from exc


@router.post("/{quiz_set_id}/publish")
def publish_quiz_set(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Publish the set. Student-facing application queries explicitly return only
    questions with review_status 'approved' inside a published set. The backend
    uses the service-role client, so this filtering is not delegated to RLS.
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
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUIZ_PUBLISHED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="quiz_set",
        subject_id=quiz_set_id,
    )
    row = updated.data[0]
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "published_at": row.get("published_at"),
    }


@router.post("/{quiz_set_id}/archive")
def archive_quiz_set(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Unpublish and hide a quiz while preserving attempts and analytics."""
    _require_teacher(profile)
    service = get_service_client()
    _teacher_quiz_set(service, quiz_set_id, profile)
    updated = (
        service.table("quiz_sets")
        .update({"status": "archived", "published_at": None})
        .eq("id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    row = updated.data[0]
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "published_at": row.get("published_at"),
    }


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
