"""Batch management + rostering (Phase 6.1).

  GET    /api/v1/public/batches?tenant_id=&course_id=&course_level_id=
                                                       — signup batch dropdown.
  GET    /api/v1/batches[?course_id=&course_level_id=] — staff; list batches.
  POST   /api/v1/batches                                — admin; create a batch.
  PATCH  /api/v1/batches/{id}                           — admin; rename / archive.
  GET    /api/v1/batches/{id}/members                   — staff; the roster.
  POST   /api/v1/batches/{id}/members                   — admin; add/restore a member.
  DELETE /api/v1/batches/{id}/members/{profile_id}      — admin; deactivate a member.

All writes go through the service-role client and are tenant-scoped in code.
Students self-select their batch at signup (handle_new_user); this API is for
staff management and correction.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_institution_admin, require_staff
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in

router = APIRouter(prefix="/api/v1", tags=["batches"])

class BatchCreate(BaseModel):
    course_id: UUID
    course_level_id: UUID
    name: str = Field(min_length=1, max_length=120)
    exam_session: str | None = Field(default=None, max_length=60)


class BatchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class MemberAdd(BaseModel):
    profile_id: UUID


def _owned_batch(service, batch_id: str, tenant_id: str) -> dict:
    row = (
        service.table("batches").select("id, course_id, course_level_id, name, status")
        .eq("id", batch_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    if row is None or not row.data:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return row.data


# ---- public (signup dropdown) ----------------------------------------------

@router.get("/public/batches")
def public_batches(tenant_id: UUID, course_id: UUID, course_level_id: UUID) -> list[dict]:
    """Active batch names for the signup dropdown, scoped to one course of an
    active institution. Only registration metadata (id + name) is exposed."""
    service = get_service_client()
    rows = (
        service.table("batches")
        .select("id, name, tenants!inner(is_active)")
        .eq("tenant_id", str(tenant_id))
        .eq("course_id", str(course_id))
        .eq("course_level_id", str(course_level_id))
        .eq("status", "active")
        .eq("tenants.is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    return [{"id": r["id"], "name": r["name"]} for r in rows]


# ---- staff / admin management ----------------------------------------------

@router.get("/batches")
def list_batches(
    course_id: UUID | None = None,
    course_level_id: UUID | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    require_staff(profile, action="view batches")
    service = get_service_client()
    query = (
        service.table("batches")
        .select("id, course_id, course_level_id, name, exam_session, status, created_at")
        .eq("tenant_id", profile.tenant_id)
    )
    if course_id is not None:
        query = query.eq("course_id", str(course_id))
    if course_level_id is not None:
        query = query.eq("course_level_id", str(course_level_id))
    return query.order("name").execute().data or []


@router.post("/batches", status_code=201)
def create_batch(
    body: BatchCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile, action="manage batches")
    service = get_service_client()
    level = (
        service.table("course_levels").select("id, course_id, is_active")
        .eq("id", str(body.course_level_id)).eq("course_id", str(body.course_id))
        .eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if level is None or not level.data or not level.data.get("is_active", True):
        raise HTTPException(status_code=404, detail="Active course level not found.")
    payload = {
        "tenant_id": profile.tenant_id,
        "course_id": str(body.course_id),
        "course_level_id": str(body.course_level_id),
        "name": body.name.strip(),
        "exam_session": (body.exam_session or None),
        "created_by": profile.user_id,
    }
    try:
        return service.table("batches").insert(payload).execute().data[0]
    except Exception as exc:  # noqa: BLE001 - unique(tenant,course,name) get-or-create
        existing = (
            service.table("batches").select("id, course_id, course_level_id, name, exam_session, status, created_at")
            .eq("tenant_id", profile.tenant_id).eq("course_id", str(body.course_id))
            .eq("course_level_id", str(body.course_level_id))
            .eq("name", body.name.strip()).maybe_single().execute()
        )
        if existing and existing.data:
            return existing.data
        raise HTTPException(status_code=409, detail="Could not create the batch.") from exc


@router.patch("/batches/{batch_id}")
def update_batch(
    batch_id: UUID, body: BatchUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_institution_admin(profile, action="manage batches")
    service = get_service_client()
    _owned_batch(service, str(batch_id), profile.tenant_id)
    updates = {k: v for k, v in {"name": body.name and body.name.strip(),
                                 "status": body.status}.items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided.")
    updated = (
        service.table("batches").update(updates)
        .eq("id", str(batch_id)).eq("tenant_id", profile.tenant_id).execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return updated.data[0]


# ---- roster view + correction ----------------------------------------------

@router.get("/batches/{batch_id}/members")
def list_members(
    batch_id: UUID, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    require_staff(profile, action="view batches")
    service = get_service_client()
    _owned_batch(service, str(batch_id), profile.tenant_id)
    members = (
        service.table("batch_memberships")
        .select("id, profile_id, membership_role, active, created_at")
        .eq("batch_id", str(batch_id)).eq("tenant_id", profile.tenant_id)
        .execute().data or []
    )
    names = {
        p["id"]: p.get("full_name")
        for p in select_all_in(
            service, "profiles", "id, full_name",
            in_column="id", values=[m["profile_id"] for m in members],
            configure=lambda q: q.eq("tenant_id", profile.tenant_id),
        )
    } if members else {}
    return [{**m, "full_name": names.get(m["profile_id"])} for m in members]


@router.get("/batches/{batch_id}/eligible-students")
def list_eligible_students(
    batch_id: UUID, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Students enrolled in the batch's exact course level, for roster repair."""
    require_institution_admin(profile, action="manage batches")
    service = get_service_client()
    batch = _owned_batch(service, str(batch_id), profile.tenant_id)
    enrollments = (
        service.table("enrollments").select("profile_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("course_id", batch["course_id"])
        .eq("course_level_id", batch["course_level_id"])
        .execute().data or []
    )
    profile_ids = [row["profile_id"] for row in enrollments if row.get("profile_id")]
    if not profile_ids:
        return []
    students = select_all_in(
        service,
        "profiles",
        "id, full_name, role",
        in_column="id",
        values=profile_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id).eq("role", "student"),
    )
    return [{"id": row["id"], "full_name": row.get("full_name")} for row in students]


@router.post("/batches/{batch_id}/members", status_code=201)
def add_member(
    batch_id: UUID, body: MemberAdd,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Add or restore a student to a batch (roster correction)."""
    require_institution_admin(profile, action="manage batches")
    service = get_service_client()
    batch = _owned_batch(service, str(batch_id), profile.tenant_id)
    if batch.get("status") != "active":
        raise HTTPException(status_code=409, detail="Archived batches cannot accept members.")
    student = (
        service.table("profiles").select("id, role")
        .eq("id", str(body.profile_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if student is None or not student.data or student.data.get("role") != "student":
        raise HTTPException(status_code=404, detail="Student not found in this institution.")
    enrollment = (
        service.table("enrollments").select("id")
        .eq("tenant_id", profile.tenant_id)
        .eq("profile_id", str(body.profile_id))
        .eq("course_id", batch["course_id"])
        .eq("course_level_id", batch["course_level_id"])
        .maybe_single().execute()
    )
    if enrollment is None or not enrollment.data:
        raise HTTPException(
            status_code=409,
            detail="Student is not enrolled in this batch's course and level.",
        )
    existing = (
        service.table("batch_memberships").select("id")
        .eq("tenant_id", profile.tenant_id).eq("batch_id", str(batch_id))
        .eq("profile_id", str(body.profile_id)).maybe_single().execute()
    )
    if existing and existing.data:
        updated = (
            service.table("batch_memberships").update({"active": True})
            .eq("id", existing.data["id"]).eq("tenant_id", profile.tenant_id).execute()
        )
        return updated.data[0]
    return (
        service.table("batch_memberships").insert({
            "tenant_id": profile.tenant_id, "batch_id": str(batch_id),
            "profile_id": str(body.profile_id), "membership_role": "student",
        }).execute().data[0]
    )


@router.delete("/batches/{batch_id}/members/{profile_id}")
def deactivate_member(
    batch_id: UUID, profile_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Deactivate a membership (soft-remove; preserves history)."""
    require_institution_admin(profile, action="manage batches")
    service = get_service_client()
    updated = (
        service.table("batch_memberships").update({"active": False})
        .eq("tenant_id", profile.tenant_id).eq("batch_id", str(batch_id))
        .eq("profile_id", str(profile_id)).execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Membership not found.")
    return {"deactivated": True}
