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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["assignments"])


def _require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only teachers can assign quizzes.")


def _require_batches_enabled() -> None:
    if not getattr(get_settings(), "batches_enabled", False):
        raise HTTPException(status_code=503, detail="Batch assignment is not enabled yet.")


def _owned_quiz(service, quiz_set_id: str, profile: CurrentProfile) -> dict:
    row = (
        service.table("quiz_sets").select("id, subject_id, status, audience_mode")
        .eq("id", quiz_set_id).eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id).maybe_single().execute()
    )
    if row is None or not row.data:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    return row.data


def _quiz_course_id(service, subject_id, tenant_id: str) -> str | None:
    if not subject_id:
        return None
    row = (
        service.table("subjects").select("course_id")
        .eq("id", subject_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    return (row.data or {}).get("course_id") if row else None


class AssignRequest(BaseModel):
    batch_ids: list[UUID] = Field(min_length=1)
    available_from: datetime | None = None
    available_to: datetime | None = None


@router.post("/{quiz_set_id}/assignments", status_code=201)
def assign_to_batches(
    quiz_set_id: UUID, body: AssignRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)
    _require_batches_enabled()
    service = get_service_client()
    quiz = _owned_quiz(service, str(quiz_set_id), profile)
    if quiz.get("status") != "published":
        raise HTTPException(status_code=400, detail="Publish the quiz before assigning it.")
    course_id = _quiz_course_id(service, quiz.get("subject_id"), profile.tenant_id)
    if not course_id:
        raise HTTPException(status_code=400, detail="This quiz is not linked to a course.")

    batch_ids = [str(b) for b in dict.fromkeys(body.batch_ids)]
    valid = select_all_in(
        service, "batches", "id", in_column="id", values=batch_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id).eq("course_id", course_id),
    )
    valid_ids = {row["id"] for row in valid}
    if set(batch_ids) - valid_ids:
        raise HTTPException(status_code=400,
                            detail="Some batches do not belong to this quiz's course.")

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
    _require_teacher(profile)
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
    _require_teacher(profile)
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
