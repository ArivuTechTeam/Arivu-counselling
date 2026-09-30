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
from pydantic import BaseModel, Field, model_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_institution_admin, require_staff
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in
from app.services.commerce_context import PROFILE_FIELDS
from app.services.tenant_features import require_profile_feature


def _require_commerce(profile: CurrentProfile) -> None:
    require_profile_feature(profile, "commerce_pack", label="Commerce paper profiles")

router = APIRouter(prefix="/api/v1", tags=["paper-profiles"])

class PaperSectionConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    question_type: str | None = Field(default=None, max_length=40)
    count: int = Field(ge=1, le=50)
    min_marks: float | None = Field(default=None, gt=0)
    max_marks: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.min_marks is not None and self.max_marks is not None and self.min_marks > self.max_marks:
            raise ValueError("min_marks cannot exceed max_marks")
        return self


class PaperFormatConfig(BaseModel):
    sections: list[PaperSectionConfig] = Field(default_factory=list, max_length=26)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    instructions: list[str] = Field(default_factory=list, max_length=20)
    numbering_style: str = Field(default="numeric", pattern="^(numeric|q_numeric|roman)$")
    currency_symbol: str | None = Field(default=None, max_length=8)
    locale: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class PaperProfileUpdate(BaseModel):
    exam_body: str | None = None
    level: str | None = None
    paper: str | None = None
    assessment_year: str | None = None
    framework: str | None = None
    format_config: PaperFormatConfig | None = None


def _cleaned_fields(body: PaperProfileUpdate) -> dict[str, str | None]:
    """Trim each field; blank -> None so an empty box clears that value."""
    out: dict[str, str | None] = {}
    for field in PROFILE_FIELDS:
        value = getattr(body, field, None)
        value = value.strip() if isinstance(value, str) else None
        out[field] = value or None
    return out


def _cleaned_format_config(body: PaperProfileUpdate) -> dict | None:
    """Return a meaningful format object, preserving omitted-vs-cleared semantics."""
    if body.format_config is None:
        return None
    config = body.format_config.model_dump(exclude_none=True)
    if not config.get("sections"):
        config.pop("sections", None)
    if not config.get("instructions"):
        config.pop("instructions", None)
    if config.get("numbering_style") == "numeric":
        config.pop("numbering_style", None)
    return config


def _present(row: dict | None) -> dict | None:
    """A profile dict limited to the commerce fields, or None if all blank."""
    if not row:
        return None
    fields = {field: row.get(field) for field in PROFILE_FIELDS}
    fields["format_config"] = row.get("format_config") or {}
    return fields if any(fields[field] for field in PROFILE_FIELDS) or fields["format_config"] else None


@router.get("/paper-profiles")
def list_paper_profiles(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    require_staff(profile, action="view paper profiles")
    _require_commerce(profile)
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
        .select(", ".join(("course_level_id", *PROFILE_FIELDS, "format_config")))
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
    _require_commerce(profile)
    service = get_service_client()
    level = (
        service.table("course_levels").select("id, course_id, name")
        .eq("id", str(course_level_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if level is None or not level.data:
        raise HTTPException(status_code=404, detail="Course level not found.")

    fields = _cleaned_fields(body)
    format_config = _cleaned_format_config(body)
    has_profile_context = any(
        fields[field] for field in PROFILE_FIELDS if field != "level"
    ) or bool(format_config)
    if not has_profile_context:
        service.table("paper_profiles").delete() \
            .eq("course_level_id", str(course_level_id)).eq("tenant_id", profile.tenant_id).execute()
        return {"profile": None}

    # Academic level is already authoritative in Course -> Level -> Subject.
    # Do not allow a duplicate free-text value to drift from that hierarchy.
    fields["level"] = level.data["name"]

    existing = (
        service.table("paper_profiles").select("id, format_config")
        .eq("course_level_id", str(course_level_id)).eq("tenant_id", profile.tenant_id)
        .maybe_single().execute()
    )
    if existing and existing.data:
        update_fields = {**fields}
        if format_config is not None:
            update_fields["format_config"] = format_config
        service.table("paper_profiles").update(update_fields) \
            .eq("id", existing.data["id"]).eq("tenant_id", profile.tenant_id).execute()
    else:
        service.table("paper_profiles").insert({
            "tenant_id": profile.tenant_id,
            "course_id": level.data["course_id"],
            "course_level_id": str(course_level_id),
            "created_by": profile.user_id,
            "format_config": format_config or {},
            **fields,
        }).execute()
    return {"profile": {**fields, "format_config": format_config if format_config is not None else (existing.data.get("format_config") if existing and existing.data else {})}}
