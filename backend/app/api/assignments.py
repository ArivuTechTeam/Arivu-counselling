"""Faculty quiz-to-batch assignment (Phase 6.1, write side).

  POST   /api/v1/quiz-sets/{id}/assignments             — assign to batches.
  GET    /api/v1/quiz-sets/{id}/assignments             — list assignments.
  DELETE /api/v1/quiz-sets/{id}/assignments/{batch_id}  — withdraw one.

A teacher assigns their own PUBLISHED quiz to one or more batches OF THE QUIZ'S
OWN COURSE (so a 2026 quiz never lands on the 2027 batch, and vice versa).
Assigning flips the quiz to audience_mode='assigned_batches'; from then on only
the assigned batches' members can see/attempt it (enforced in the student read
paths). Gated by BATCHES_ENABLED. Idempotent per (quiz, batch).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.role_checks import require_teacher
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in
from app.services.tenant_features import require_profile_feature

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["assignments"])


def _require_batches_enabled(
    profile: CurrentProfile, *, legacy_master_check: bool = False
) -> None:
    if profile.tenant_feature_flags is None:
        if legacy_master_check and not getattr(get_settings(), "batches_enabled", False):
            raise HTTPException(status_code=503, detail="Batch assignment is not enabled yet.")
        return
    require_profile_feature(profile, "batches", label="Batch assignment")


def _managed_batch_ids(service, profile: CurrentProfile) -> set[str]:
    rows = (
        service.table("batch_memberships").select("batch_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("profile_id", profile.user_id)
        .eq("membership_role", "teacher")
        .eq("active", True)
        .execute().data or []
    )
    return {str(row["batch_id"]) for row in rows}


def _owned_quiz(service, quiz_set_id: str, profile: CurrentProfile) -> dict:
    row = (
        service.table("quiz_sets").select("id, subject_id, status, audience_mode")
        .eq("id", quiz_set_id).eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id).maybe_single().execute()
    )
    if row is None or not row.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    return row.data


def _quiz_academic_scope(service, subject_id, tenant_id: str) -> tuple[str | None, str | None]:
    if not subject_id:
        return None, None
    row = (
        service.table("subjects").select("course_id, course_level_id")
        .eq("id", subject_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    data = (row.data or {}) if row else {}
    return data.get("course_id"), data.get("course_level_id")


class AssignRequest(BaseModel):
    batch_ids: list[UUID] = Field(min_length=1)
    available_from: datetime | None = None
    available_to: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self):
        if self.available_from and self.available_to and self.available_to <= self.available_from:
            raise ValueError("available_to must be after available_from")
        return self


@router.get("/{quiz_set_id}/eligible-batches")
def list_eligible_batches(
    quiz_set_id: UUID, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Only active batches in the quiz subject's exact course and level."""
    require_teacher(profile, action="assign quizzes")
    _require_batches_enabled(profile, legacy_master_check=True)
    service = get_service_client()
    quiz = _owned_quiz(service, str(quiz_set_id), profile)
    course_id, course_level_id = _quiz_academic_scope(
        service, quiz.get("subject_id"), profile.tenant_id
    )
    if not course_id or not course_level_id:
        return []
    managed_ids = sorted(_managed_batch_ids(service, profile))
    if profile.tenant_feature_flags is None:
        managed_ids = [
            str(row["id"])
            for row in (
                service.table("batches").select("id")
                .eq("tenant_id", profile.tenant_id).execute().data or []
            )
        ]
    if not managed_ids:
        return []
    return select_all_in(
        service, "batches",
        "id, course_id, course_level_id, name, exam_session, status, created_at",
        in_column="id", values=managed_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id)
        .eq("course_id", course_id).eq("course_level_id", course_level_id)
        .eq("status", "active"),
    )


@router.post("/{quiz_set_id}/assignments", status_code=201)
def assign_to_batches(
    quiz_set_id: UUID, body: AssignRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_teacher(profile, action="assign quizzes")
    _require_batches_enabled(profile, legacy_master_check=True)
    service = get_service_client()
    quiz = _owned_quiz(service, str(quiz_set_id), profile)
    if quiz.get("status") != "published":
        raise HTTPException(status_code=400, detail="Publish the quiz before assigning it.")
    course_id, course_level_id = _quiz_academic_scope(
        service, quiz.get("subject_id"), profile.tenant_id
    )
    if not course_id or not course_level_id:
        raise HTTPException(status_code=400, detail="This quiz is not linked to a course level.")

    batch_ids = [str(b) for b in dict.fromkeys(body.batch_ids)]
    if (
        profile.tenant_feature_flags is not None
        and set(batch_ids) - _managed_batch_ids(service, profile)
    ):
        raise HTTPException(
            status_code=403,
            detail="You can assign quizzes only to batches you manage.",
        )
    valid = select_all_in(
        service, "batches", "id", in_column="id", values=batch_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id)
        .eq("course_id", course_id)
        .eq("course_level_id", course_level_id)
        .eq("status", "active"),
    )
    valid_ids = {row["id"] for row in valid}
    if set(batch_ids) - valid_ids:
        raise HTTPException(status_code=400,
                            detail="Some batches do not belong to this quiz's active course level.")

    window = {
        "available_from": body.available_from.isoformat() if body.available_from else None,
        "available_to": body.available_to.isoformat() if body.available_to else None,
        "status": "active",
    }
    saved = []
    for batch_id in batch_ids:
        existing = (
            service.table("quiz_assignments").select("id")
            .eq("tenant_id", profile.tenant_id).eq("quiz_set_id", str(quiz_set_id))
            .eq("batch_id", batch_id).maybe_single().execute()
        )
        if existing and existing.data:
            saved.append(
                service.table("quiz_assignments").update(window)
                .eq("id", existing.data["id"]).eq("tenant_id", profile.tenant_id)
                .execute().data[0]
            )
        else:
            saved.append(
                service.table("quiz_assignments").insert({
                    "tenant_id": profile.tenant_id, "quiz_set_id": str(quiz_set_id),
                    "batch_id": batch_id, "created_by": profile.user_id, **window,
                }).execute().data[0]
            )

    # From now on this quiz is batch-restricted (enforced in the student paths).
    service.table("quiz_sets").update({"audience_mode": "assigned_batches"}) \
        .eq("id", str(quiz_set_id)).eq("tenant_id", profile.tenant_id) \
        .eq("created_by", profile.user_id).execute()
    return {"quiz_set_id": str(quiz_set_id), "audience_mode": "assigned_batches",
            "assignments": saved}


@router.get("/{quiz_set_id}/assignments")
def list_assignments(
    quiz_set_id: UUID, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    require_teacher(profile, action="view quiz assignments")
    _require_batches_enabled(profile)
    service = get_service_client()
    _owned_quiz(service, str(quiz_set_id), profile)
    return (
        service.table("quiz_assignments")
        .select("id, batch_id, available_from, available_to, status, created_at")
        .eq("tenant_id", profile.tenant_id).eq("quiz_set_id", str(quiz_set_id))
        .execute().data or []
    )


@router.delete("/{quiz_set_id}/assignments/{batch_id}")
def withdraw_assignment(
    quiz_set_id: UUID, batch_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Withdraw one batch's assignment (soft: status='withdrawn'). The quiz stays
    audience_mode='assigned_batches' — it is simply visible to no batch until
    reassigned, never silently reverting to course-wide visibility."""
    require_teacher(profile, action="withdraw quiz assignments")
    _require_batches_enabled(profile)
    service = get_service_client()
    _owned_quiz(service, str(quiz_set_id), profile)
    updated = (
        service.table("quiz_assignments").update({"status": "withdrawn"})
        .eq("tenant_id", profile.tenant_id).eq("quiz_set_id", str(quiz_set_id))
        .eq("batch_id", str(batch_id)).execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    return {"withdrawn": True}
