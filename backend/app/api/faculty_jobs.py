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

router = APIRouter(prefix="/api/v1/faculty-jobs", tags=["faculty-jobs"])


def require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(403, "Only teachers can access these tasks.")


class GenerateJobRequest(BlueprintGenerateRequest):
    request_key: UUID
    analysis_job_id: UUID | None = None


@router.get("")
def list_jobs(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    if not get_settings().faculty_jobs_enabled:
        return {"enabled": False, "jobs": []}
    columns = PUBLIC_COLUMNS.replace("result,", "quiz_set_id:result->>quiz_set_id,")
    rows = (get_service_client().table("faculty_jobs").select(columns)
            .eq("tenant_id", profile.tenant_id).eq("created_by", profile.user_id)
            .order("created_at", desc=True).limit(50).execute().data or [])
    return {"enabled": True, "jobs": [public_job(row) for row in rows]}


@router.post("", status_code=202)
def create_job(req: GenerateJobRequest, profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_teacher(profile)
    if not get_settings().faculty_jobs_enabled:
        raise HTTPException(503, "Background processing is not enabled yet.")
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
