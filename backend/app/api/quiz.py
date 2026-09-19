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
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all, select_all_in
from app.services.blueprint import generate_blueprint_quiz
from app.services.events import QUIZ_PUBLISHED, log_event
from app.services.generation import generate_quiz
from app.services.generation_jobs import (
    create_final_generation_job,
    create_generation_job,
    launch_job,
)
from app.services.document_profile import profile_document, profile_to_summary
from app.services.ai_call_logging import ai_call_context
from app.services.llm import LLMError
from app.services.quiz_generator_service import QuizGeneratorService
from app.services.rate_limit import (
    BLUEPRINT_GENERATION,
    QUIZ_GENERATION,
    TOPIC_EXTRACTION,
    enforce_ai_rate_limit,
)
from app.services.review import get_quiz_set_detail
from app.services.topics import extract_topic_details
from app.services.topic_capacity import selectable_topic_choices

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["quiz"])

CORE_TYPES = {"mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"}
QUIZ_SET_PAGE_SIZE_MAX = 100


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
# Small documents use one grounded rich extraction call. Large ones are analysed
# in the background (chunk -> MAP -> REDUCE). Both paths expose the same verified
# topic evidence and capacity guidance before the teacher generates a quiz.


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
    """Start durable, cost-bounded topic analysis and return its polling id.

    The worker performs document reading after the job exists, so a browser
    refresh cannot orphan a long request. All supported document sizes share
    the same resumable zero/one-call outline path.
    """
    if profile.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can analyze documents.")

    service = get_service_client()
    doc = _owned_document(service, req.document_id, profile)

    prefer_local_outline = doc["file_type"].lower() == "pdf"
    # DOCX cannot use the local PDF outline path, so reserve its one provider
    # call before accepting the job. PDF calls are reserved by the worker only
    # if deterministic outline extraction is inconclusive.
    if not prefer_local_outline:
        enforce_ai_rate_limit(
            profile=profile,
            endpoint=TOPIC_EXTRACTION,
            hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
            action_label="document analysis",
        )
    job_id = create_generation_job(
        document_id=req.document_id,
        tenant_id=profile.tenant_id,
        created_by=profile.user_id,
        params={
            "prefer_local_outline": prefer_local_outline,
            "profile_rate_limit_reserved": not prefer_local_outline,
            "single_call_ai_outline": True,
            "allow_multi_call_fallback": False,
        },
    )
    return {
        "mode": "job",
        "document_id": req.document_id,
        "job_id": job_id,
        "status": "queued",
    }


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

    is_final_generation = ((job.get("params") or {}).get("kind") == "final_generation")
    message = (
        "Quiz generation stopped before it finished. Retry to continue."
        if is_final_generation
        else "Analysis stopped before it finished. Retry to continue saved sections."
    )
    now = datetime.now(timezone.utc).isoformat()
    if not is_final_generation:
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
    document_profile = (job.get("params") or {}).get("document_profile") or {}
    topic_choices = selectable_topic_choices(blueprint.get("topics") or [])
    topics = [
        {
            "name": topic["name"],
            "group_name": topic.get("group_name") or "",
            "subtopics": topic.get("subtopics") or [],
            "page_ranges": topic.get("page_ranges") or [],
            "suggested_question_limit": topic["suggested_question_limit"],
        }
        for topic in topic_choices
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
        "analysis_mode": blueprint.get("analysis_mode")
        or (job.get("params") or {}).get("analysis_mode"),
        "source_quality_warnings": document_profile.get("source_quality_warnings") or [],
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
    launch_job(job_id, profile.tenant_id)
    return {"job_id": job_id, "status": "queued"}


class JobGenerateRequest(BaseModel):
    subject_id: str
    chapter_name: str
    selected_topics: list[BlueprintTopicIn] = Field(default_factory=list)
    # Optional in per-topic mode (see BlueprintGenerateRequest.type_counts).
    type_counts: dict[str, int] = Field(default_factory=dict)
    cognitive_level: Literal["theory", "practical", "mixed"] = "mixed"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


def _queue_final_generation(
    *,
    document_id: str,
    source_job_id: str | None,
    req: BlueprintGenerateRequest | JobGenerateRequest,
    profile: CurrentProfile,
) -> dict:
    """Validate and queue the final LLM call rather than holding an HTTP request.

    AI providers may legitimately take several minutes for a 15–50 question
    exact-mix quiz (including the corrective validation retry).  Returning a
    durable job immediately avoids browser/proxy timeouts and is safe to retry.
    """
    if profile.role != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can generate quizzes.")
    if not req.chapter_name.strip():
        raise HTTPException(status_code=400, detail="Chapter name is required.")
    selected, type_counts, total, question_types = _resolve_blueprint_plan(
        req.selected_topics, req.type_counts
    )
    if total < 1 or total > 50 or len(req.selected_topics) > total:
        raise HTTPException(status_code=400, detail="Choose between 1 and 50 questions and no more topics than questions.")
    if source_job_id:
        job = _owned_job(get_service_client(), source_job_id, profile)
        if job.get("status") != "completed" or not job.get("master_blueprint"):
            raise HTTPException(status_code=400, detail="This document analysis is not ready yet.")

    request = {
        "source_job_id": source_job_id,
        "subject_id": req.subject_id,
        "chapter_name": req.chapter_name.strip(),
        "selected_topics": selected,
        "total_questions": total,
        "question_types": question_types,
        "type_counts": type_counts,
        "cognitive_level": req.cognitive_level,
        "difficulty": req.difficulty,
    }
    job_id, created = create_final_generation_job(
        document_id=document_id,
        tenant_id=profile.tenant_id,
        created_by=profile.user_id,
        request=request,
        launch=False,
    )
    if created:
        try:
            enforce_ai_rate_limit(
                profile=profile,
                endpoint=BLUEPRINT_GENERATION,
                hourly_limit=get_settings().rate_limit_blueprint_per_hour,
                action_label="blueprint generation",
            )
        except Exception:
            # Do not strand a queued job when the rate limiter denies it.
            get_service_client().table("quiz_generation_jobs").update(
                {"status": "failed", "phase": "failed", "error_message": "Generation limit reached. Try again later."}
            ).eq("id", job_id).eq("tenant_id", profile.tenant_id).execute()
            raise
        launch_job(job_id, profile.tenant_id)
    return {"job_id": job_id, "status": "queued", "created": created}


@router.post("/generate-blueprint/async")
def queue_blueprint_generation(
    req: BlueprintGenerateRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    return _queue_final_generation(
        document_id=req.document_id, source_job_id=None, req=req, profile=profile
    )


@router.post("/generation-jobs/{job_id}/generate-async")
def queue_generation_from_job(
    job_id: str,
    req: JobGenerateRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    job = _owned_job(get_service_client(), job_id, profile)
    return _queue_final_generation(
        document_id=job["document_id"], source_job_id=job_id, req=req, profile=profile
    )


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
    page: int = 1,
    page_size: int = 50,
) -> list[dict]:
    """List one bounded page of the teacher's quiz sets, newest first."""
    _require_teacher(profile)
    if page < 1 or page_size < 1 or page_size > QUIZ_SET_PAGE_SIZE_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                "page must be positive and page_size must be between 1 and "
                f"{QUIZ_SET_PAGE_SIZE_MAX}."
            ),
        )
    service = get_service_client()
    start = (page - 1) * page_size
    rows = (
        service.table("quiz_sets")
        .select("id, title, status, created_at, published_at")
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .neq("status", "archived")
        .order("created_at", desc=True)
        .range(start, start + page_size - 1)
        .execute()
        .data
        or []
    )
    return rows


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
    variants = select_all(
        service,
        "quiz_variants",
        "id",
        configure=lambda query: query.eq("quiz_set_id", quiz_set_id).eq(
            "tenant_id", profile.tenant_id
        ),
    )
    variant_ids = [row["id"] for row in variants]
    if not variant_ids:
        raise HTTPException(
            status_code=400,
            detail="This quiz does not contain any variants.",
        )
    links = select_all_in(
        service,
        "quiz_variant_questions",
        "id, variant_id, question_id, marks_override",
        in_column="variant_id",
        values=variant_ids,
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
    )
    question_ids = list({str(row["question_id"]) for row in links})
    questions = (
        select_all_in(
            service,
            "questions",
            "id, review_status, marks",
            in_column="id",
            values=question_ids,
            configure=lambda query: query
            .eq("tenant_id", profile.tenant_id)
            .eq("created_by", profile.user_id),
        )
        if question_ids
        else []
    )
    question_by_id = {str(row["id"]): row for row in questions}
    if len(question_by_id) != len(question_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more quiz questions are unavailable. Review the quiz before publishing.",
        )
    unresolved = [
        row
        for row in questions
        if row.get("review_status") not in {"approved", "rejected"}
    ]
    if unresolved:
        raise HTTPException(
            status_code=400,
            detail=(
                "Review every question before publishing. Approve, reject, edit, "
                "or regenerate the remaining questions first."
            ),
        )

    approved_marks_by_variant: dict[str, float] = {
        str(variant_id): 0.0 for variant_id in variant_ids
    }
    approved_count_by_variant: dict[str, int] = {
        str(variant_id): 0 for variant_id in variant_ids
    }
    for link in links:
        question = question_by_id[str(link["question_id"])]
        if question.get("review_status") != "approved":
            continue
        variant_id = str(link["variant_id"])
        approved_marks_by_variant[variant_id] += float(
            link.get("marks_override") or question.get("marks") or 1
        )
        approved_count_by_variant[variant_id] += 1

    if any(count == 0 for count in approved_count_by_variant.values()):
        raise HTTPException(
            status_code=400,
            detail="Every quiz variant must contain at least one approved question.",
        )

    # Keep the persisted denominator aligned with the exact questions students
    # can take. If an update fails, the set remains a draft and a retry is safe.
    for variant_id, total_marks in approved_marks_by_variant.items():
        updated_variant = (
            service.table("quiz_variants")
            .update({"total_marks": total_marks})
            .eq("id", variant_id)
            .eq("tenant_id", profile.tenant_id)
            .execute()
        )
        if not updated_variant.data:
            raise HTTPException(
                status_code=500,
                detail="Could not finalize quiz marks. Please try publishing again.",
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
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    question_ids = list({link["question_id"] for link in links})
    if not question_ids:
        return {"approved": 0}

    eligible_rows = (
        service.table("questions")
        .select("id,verification_status")
        .in_("id", question_ids)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .eq("review_status", "pending_review")
        .execute()
        .data
        or []
    )
    eligible_ids = [
        row["id"]
        for row in eligible_rows
        if row.get("verification_status") != "unsupported"
    ]
    if not eligible_ids:
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
        .in_("id", eligible_ids)
        .eq("review_status", "pending_review")
        .eq("tenant_id", profile.tenant_id)
        .execute()
    )
    return {"approved": len(updated.data or [])}
