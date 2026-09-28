from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.quiz import BlueprintGenerateRequest, _resolve_blueprint_plan
from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.faculty_jobs import PUBLIC_COLUMNS, enqueue, load_owned, public_job
from app.services.quiz_generator_service import QuizGeneratorService
from app.services.tenant_features import profile_feature_enabled, require_profile_feature
from app.lib.supabase_queries import select_all_in

router = APIRouter(prefix="/api/v1/faculty-jobs", tags=["faculty-jobs"])


def require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(403, "Only teachers can access these tasks.")


class GenerateJobRequest(BlueprintGenerateRequest):
    request_key: UUID
    analysis_job_id: UUID | None = None


class RegenerateJobRequest(BaseModel):
    request_key: UUID
    quiz_set_id: UUID


@router.get("")
def list_jobs(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    enabled = (
        get_settings().faculty_jobs_enabled
        if profile.tenant_feature_flags is None
        else profile_feature_enabled(profile, "faculty_jobs")
    )
    if not enabled:
        return {"enabled": False, "jobs": []}
    columns = PUBLIC_COLUMNS.replace("result,", "quiz_set_id:result->>quiz_set_id,")
    service = get_service_client()
    rows = (service.table("faculty_jobs").select(columns)
            .eq("tenant_id", profile.tenant_id).eq("created_by", profile.user_id)
            .order("created_at", desc=True).limit(50).execute().data or [])
    jobs = [public_job(row) for row in rows]
    quiz_ids = sorted({job["result"]["quiz_set_id"] for job in jobs if job.get("result") and job["result"].get("quiz_set_id")})
    if quiz_ids:
        quizzes = select_all_in(
            service, "quiz_sets", "id, status", in_column="id", values=quiz_ids,
            configure=lambda query: query.eq("tenant_id", profile.tenant_id).eq("created_by", profile.user_id),
        )
        status_by_id = {str(quiz["id"]): quiz["status"] for quiz in quizzes}
        for job in jobs:
            if job.get("result"):
                job["result"]["quiz_status"] = status_by_id.get(job["result"]["quiz_set_id"])
    return {"enabled": True, "jobs": jobs}


@router.post("", status_code=202)
def create_job(req: GenerateJobRequest, profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    if profile.tenant_feature_flags is None:
        if not get_settings().faculty_jobs_enabled:
            raise HTTPException(503, "Background processing is not enabled yet.")
    else:
        require_profile_feature(profile, "faculty_jobs", label="Background processing")
    selected, counts, total, types = _resolve_blueprint_plan(req.selected_topics, req.type_counts)
    if not req.chapter_name.strip() or not 1 <= total <= 50 or len(selected) > total:
        raise HTTPException(400, "Choose a chapter and between 1 and 50 questions with a valid topic allocation.")
    request = req.model_dump(mode="json", exclude={"request_key"})
    request.update(selected_topics=selected, type_counts=counts, total_questions=total, question_types=types)
    kind = "blueprint"
    if req.analysis_job_id:
        try:
            job = QuizGeneratorService()._load_ready_job(str(req.analysis_job_id), profile)
        except ValueError as exc:
            raise HTTPException(400, "The selected document analysis is not available or ready.") from exc
        if job["document_id"] != req.document_id:
            raise HTTPException(400, "This analysis belongs to a different document.")
        kind = "analysis_quiz"
    return enqueue(profile, str(req.request_key), kind, request)


@router.post("/regenerate", status_code=202)
def create_regeneration_job(
    req: RegenerateJobRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Queue whole-quiz regeneration without keeping an HTTP request open."""
    require_teacher(profile)
    settings = get_settings()
    if not getattr(settings, "regenerate_set_enabled", False):
        raise HTTPException(404, "Not found.")
    if profile.tenant_feature_flags is None:
        if not settings.faculty_jobs_enabled:
            raise HTTPException(503, "Background processing is not enabled yet.")
    else:
        require_profile_feature(profile, "faculty_jobs", label="Background processing")
    service = get_service_client()
    response = (
        service.table("quiz_sets")
        .select("id,status,subject_id,document_id,released_at")
        .eq("id", str(req.quiz_set_id))
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    quiz = response.data if response else None
    if not quiz:
        raise HTTPException(404, "Quiz set not found.")
    if quiz.get("status") != "draft" or quiz.get("released_at") is not None:
        raise HTTPException(409, "Only an unreleased draft can be regenerated. Duplicate the quiz first.")
    if not quiz.get("subject_id") or not quiz.get("document_id"):
        raise HTTPException(400, "This quiz is not linked to its source document and cannot be regenerated.")
    return enqueue(
        profile,
        str(req.request_key),
        "regenerate_set",
        {
            "quiz_set_id": str(req.quiz_set_id),
            "subject_id": str(quiz["subject_id"]),
            "document_id": str(quiz["document_id"]),
        },
    )


@router.get("/{job_id}")
def get_job(job_id: UUID, profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    return load_owned(str(job_id), profile)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: UUID, profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    load_owned(str(job_id), profile)
    get_service_client().rpc("update_faculty_job", {
        "p_id": str(job_id), "p_tenant": profile.tenant_id, "p_actor": profile.user_id,
        "p_token": None, "p_action": "cancel",
    }).execute()
    return load_owned(str(job_id), profile)
