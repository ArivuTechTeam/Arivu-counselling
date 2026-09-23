"""Admin: set each course's official exam-scoring standard (Phase 6.2-5).

  GET /api/v1/scoring-presets        — the catalog of official presets (staff).
  GET /api/v1/exam-standards         — every course + its current standard (staff).
  PUT /api/v1/exam-standards/{id}    — set a course's standard (admin).

Picking a preset get-or-creates the matching scoring policy for the tenant and
links it to the course; the exam simulator then scores by that standard. No raw
JSON, no SQL — one dropdown per course.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all_in
from app.services.scoring_presets import SCORING_PRESETS, preset_rules

router = APIRouter(prefix="/api/v1", tags=["exam-standards"])

_STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _require_staff(profile: CurrentProfile) -> None:
    if profile.role not in _STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only.")


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role != "institution_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only institution admins can set exam standards.")


class ExamStandardUpdate(BaseModel):
    preset_key: str | None = None  # None clears the standard (default full/zero)


@router.get("/scoring-presets")
def list_scoring_presets(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    _require_staff(profile)
    return [
        {"key": key, "name": preset["name"], "description": preset["description"]}
        for key, preset in SCORING_PRESETS.items()
    ]


@router.get("/exam-standards")
def list_exam_standards(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    _require_staff(profile)
    service = get_service_client()
    courses = (
        service.table("courses").select("id, name, exam_scoring_policy_id")
        .eq("tenant_id", profile.tenant_id).order("name").execute().data or []
    )
    policy_ids = [c["exam_scoring_policy_id"] for c in courses if c.get("exam_scoring_policy_id")]
    preset_by_policy: dict[str, str | None] = {}
    if policy_ids:
        for row in select_all_in(
            service, "scoring_policies", "id, rules", in_column="id", values=policy_ids,
            configure=lambda q: q.eq("tenant_id", profile.tenant_id),
        ):
            preset_by_policy[row["id"]] = (row.get("rules") or {}).get("preset_key")
    return [
        {
            "course_id": c["id"],
            "course_name": c["name"],
            "preset_key": preset_by_policy.get(c.get("exam_scoring_policy_id")),
        }
        for c in courses
    ]


@router.put("/exam-standards/{course_id}")
def set_exam_standard(
    course_id: UUID, body: ExamStandardUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    course = (
        service.table("courses").select("id")
        .eq("id", str(course_id)).eq("tenant_id", profile.tenant_id).maybe_single().execute()
    )
    if course is None or not course.data:
        raise HTTPException(status_code=404, detail="Course not found.")

    if body.preset_key is None:
        service.table("courses").update({"exam_scoring_policy_id": None}) \
            .eq("id", str(course_id)).eq("tenant_id", profile.tenant_id).execute()
        return {"preset_key": None}

    preset = SCORING_PRESETS.get(body.preset_key)
    if preset is None:
        raise HTTPException(status_code=400, detail="Unknown exam standard.")

    # Get-or-create the tenant's policy for this preset (unique per tenant+name).
    existing = (
        service.table("scoring_policies").select("id")
        .eq("tenant_id", profile.tenant_id).eq("name", preset["name"]).maybe_single().execute()
    )
    if existing and existing.data:
        policy_id = existing.data["id"]
    else:
        try:
            policy_id = service.table("scoring_policies").insert({
                "tenant_id": profile.tenant_id, "name": preset["name"],
                "rules": preset_rules(body.preset_key), "created_by": profile.user_id,
            }).execute().data[0]["id"]
        except Exception:  # noqa: BLE001 - recover a concurrent get-or-create race
            again = (
                service.table("scoring_policies").select("id")
                .eq("tenant_id", profile.tenant_id).eq("name", preset["name"]).maybe_single().execute()
            )
            if not (again and again.data):
                raise
            policy_id = again.data["id"]

    service.table("courses").update({"exam_scoring_policy_id": policy_id}) \
        .eq("id", str(course_id)).eq("tenant_id", profile.tenant_id).execute()
    return {"preset_key": body.preset_key, "policy_id": policy_id}
