"""Teacher-facing API for durable exam-paper generation."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.role_checks import require_staff, require_teacher
from app.lib.supabase import get_service_client
from app.services.faculty_jobs import enqueue_generated_paper


router = APIRouter(prefix="/api/v1/generated-papers", tags=["generated-papers"])


class GeneratePaperRequest(BaseModel):
    request_key: UUID
    course_level_id: UUID
    subject_id: UUID
    mode: Literal["exact_mark", "candidate_ai"]
    requested_total_marks: float = Field(gt=0, le=1000)
    question_count: int = Field(ge=1, le=50)
    chapter_ids: list[UUID] = Field(default_factory=list, max_length=50)
    question_types: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("requested_total_marks")
    @classmethod
    def half_mark_grid(cls, value: float) -> float:
        if abs(round(value * 2) - value * 2) > 1e-6:
            raise ValueError("Total marks must use whole or half marks.")
        return value


class GeneratedPaperOut(BaseModel):
    id: str
    course_level_id: str
    subject_id: str
    mode: str
    requested_total_marks: float
    selected_question_ids: list[str] = Field(default_factory=list)
    status: str
    instructions_text: str | None = None
    paper_payload: dict | None = None
    error_message: str | None = None
    created_by: str
    created_at: str
    completed_at: str | None = None


def _enabled() -> None:
    settings = get_settings()
    if not settings.paper_bank_enabled or not settings.faculty_jobs_enabled:
        raise HTTPException(503, "Exam-paper generation is not enabled yet.")


def _owned_or_tenant_row(paper_id: str, profile: CurrentProfile) -> dict:
    query = (
        get_service_client().table("generated_papers").select("*")
        .eq("id", paper_id).eq("tenant_id", profile.tenant_id)
    )
    if profile.role == "teacher":
        query = query.eq("created_by", profile.user_id)
    response = query.maybe_single().execute()
    if response is None or not response.data:
        raise HTTPException(404, "Generated paper not found.")
    return response.data


@router.post("", status_code=202)
def start_generated_paper(
    body: GeneratePaperRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_teacher(profile, action="generate exam papers")
    _enabled()
    request = body.model_dump(mode="json", exclude={"request_key"})
    return enqueue_generated_paper(profile, str(body.request_key), request)


@router.get("", response_model=list[GeneratedPaperOut])
def list_generated_papers(
    course_level_id: UUID = Query(...),
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    require_staff(profile, action="view generated papers")
    _enabled()
    query = (
        get_service_client().table("generated_papers").select("*")
        .eq("tenant_id", profile.tenant_id)
        .eq("course_level_id", str(course_level_id))
    )
    if profile.role == "teacher":
        query = query.eq("created_by", profile.user_id)
    return query.order("created_at", desc=True).limit(50).execute().data or []


@router.get("/{paper_id}", response_model=GeneratedPaperOut)
def get_generated_paper(
    paper_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_staff(profile, action="view generated papers")
    _enabled()
    return _owned_or_tenant_row(str(paper_id), profile)
