"""Admin: bind each course's commerce paper profile (Phase 6.3-D).

  GET /api/v1/paper-profiles          - every course + its current profile (staff).
  PUT /api/v1/paper-profiles/{course} - set/clear a course's profile (admin).

A paper profile is the single place commerce context lives (exam body / level /
paper / assessment year / accounting framework). Generation reads it into the
prompt only when COMMERCE_PACK_ENABLED is on (Phase 6.3-B); with the flag off it
is inert data. One profile per course; sending an all-blank body clears it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.commerce_context import PROFILE_FIELDS

router = APIRouter(prefix="/api/v1", tags=["paper-profiles"])

_STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _require_staff(profile: CurrentProfile) -> None:
    if profile.role not in _STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only.")


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role != "institution_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only institution admins can set paper profiles.",
        )


class PaperProfileUpdate(BaseModel):
    exam_body: str | None = None
    level: str | None = None
    paper: str | None = None
    assessment_year: str | None = None
    framework: str | None = None


def _cleaned_fields(body: PaperProfileUpdate) -> dict[str, str | None]:
    """Trim each field; blank -> None so an empty box clears that value."""
    out: dict[str, str | None] = {}
    for field in PROFILE_FIELDS:
        value = getattr(body, field, None)
        value = value.strip() if isinstance(value, str) else None
        out[field] = value or None
    return out


def _present(row: dict | None) -> dict | None:
    """A profile dict limited to the commerce fields, or None if all blank."""
    if not row:
        return None
    fields = {field: row.get(field) for field in PROFILE_FIELDS}
    return fields if any(fields.values()) else None


@router.get("/paper-profiles")
def list_paper_profiles(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    _require_staff(profile)
    service = get_service_client()
    courses = (
        service.table("courses").select("id, name")
        .eq("tenant_id", profile.tenant_id).order("name").execute().data or []
    )
    profiles = (
        service.table("paper_profiles")
        .select(", ".join(("course_id", *PROFILE_FIELDS)))
        .eq("tenant_id", profile.tenant_id).execute().data or []
    )
    by_course = {p["course_id"]: p for p in profiles}
    return [
        {
            "course_id": c["id"],
            "course_name": c["name"],
            "profile": _present(by_course.get(c["id"])),
        }
        for c in courses
    ]


@router.put("/paper-profiles/{course_id}")
def set_paper_profile(
    course_id: UUID,
    body: PaperProfileUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    course = (
        service.table("courses").select("id")
        .eq("id", str(course_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if course is None or not course.data:
        raise HTTPException(status_code=404, detail="Course not found.")

    fields = _cleaned_fields(body)
    if not any(fields.values()):
        service.table("paper_profiles").delete() \
            .eq("course_id", str(course_id)).eq("tenant_id", profile.tenant_id).execute()
        return {"profile": None}

    existing = (
        service.table("paper_profiles").select("id")
        .eq("course_id", str(course_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if existing and existing.data:
        service.table("paper_profiles").update(fields).eq("id", existing.data["id"]).execute()
    else:
        service.table("paper_profiles").insert({
            "tenant_id": profile.tenant_id,
            "course_id": str(course_id),
            "created_by": profile.user_id,
            **fields,
        }).execute()
    return {"profile": fields}
