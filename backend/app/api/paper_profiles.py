"""Admin: bind each course level's commerce paper profile (Phase 6.3-D).

  GET /api/v1/paper-profiles         - every course level + profile (staff).
  PUT /api/v1/paper-profiles/{level} - set/clear a level's profile (admin).

A paper profile is the single place commerce context lives (exam body / level /
paper / assessment year / accounting framework). Generation reads it into the
prompt only when COMMERCE_PACK_ENABLED is on (Phase 6.3-B); with the flag off it
is inert data. One profile per course level; sending an all-blank body clears it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_institution_admin, require_staff
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in
from app.services.commerce_context import PROFILE_FIELDS

router = APIRouter(prefix="/api/v1", tags=["paper-profiles"])

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
    require_staff(profile, action="view paper profiles")
    service = get_service_client()
    levels = (
        service.table("course_levels").select("id, course_id, name")
        .eq("tenant_id", profile.tenant_id).order("name").execute().data or []
    )
    course_ids = [level["course_id"] for level in levels]
    courses = select_all_in(
        service, "courses", "id, name", in_column="id", values=course_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    ) if course_ids else []
    course_names = {course["id"]: course["name"] for course in courses}
    profiles = (
        service.table("paper_profiles")
        .select(", ".join(("course_level_id", *PROFILE_FIELDS)))
        .eq("tenant_id", profile.tenant_id).execute().data or []
    )
    by_level = {p["course_level_id"]: p for p in profiles}
    return [
        {
            "course_id": level["course_id"],
            "course_name": course_names.get(level["course_id"], "Course"),
            "course_level_id": level["id"],
            "level_name": level["name"],
            "profile": _present(by_level.get(level["id"])),
        }
        for level in levels
    ]


@router.put("/paper-profiles/{course_level_id}")
def set_paper_profile(
    course_level_id: UUID,
    body: PaperProfileUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_institution_admin(profile, action="set paper profiles")
    service = get_service_client()
    level = (
        service.table("course_levels").select("id, course_id, name")
        .eq("id", str(course_level_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if level is None or not level.data:
        raise HTTPException(status_code=404, detail="Course level not found.")

    fields = _cleaned_fields(body)
    has_profile_context = any(
        fields[field] for field in PROFILE_FIELDS if field != "level"
    )
    if not has_profile_context:
        service.table("paper_profiles").delete() \
            .eq("course_level_id", str(course_level_id)).eq("tenant_id", profile.tenant_id).execute()
        return {"profile": None}

    # Academic level is already authoritative in Course -> Level -> Subject.
    # Do not allow a duplicate free-text value to drift from that hierarchy.
    fields["level"] = level.data["name"]

    existing = (
        service.table("paper_profiles").select("id")
        .eq("course_level_id", str(course_level_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if existing and existing.data:
        service.table("paper_profiles").update(fields) \
            .eq("id", existing.data["id"]).eq("tenant_id", profile.tenant_id).execute()
    else:
        service.table("paper_profiles").insert({
            "tenant_id": profile.tenant_id,
            "course_id": level.data["course_id"],
            "course_level_id": str(course_level_id),
            "created_by": profile.user_id,
            **fields,
        }).execute()
    return {"profile": fields}
