"""
Academic hierarchy API (courses / subjects).

  GET    /api/v1/public/courses?tenant_id=...  — UNauthenticated; signup dropdown.
  GET    /api/v1/courses                        — staff; teacher sees only their
                                                  mapped course(s).
  POST   /api/v1/courses                        — admin; create a course.
  POST   /api/v1/subjects                       — admin; create a subject.
  DELETE /api/v1/courses/{id}                    — admin; delete a course.
  DELETE /api/v1/subjects/{id}                   — admin; delete a subject.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1", tags=["academics"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}
ADMIN_ROLES = {"institution_admin", "super_admin"}


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only institution admins can manage courses and subjects.",
        )


def _subjects_for(service, course_id: str, tenant_id: str) -> list[dict]:
    return (
        service.table("subjects")
        .select("id, name")
        .eq("course_id", course_id)
        .eq("tenant_id", tenant_id)
        .order("name")
        .execute()
        .data
        or []
    )


@router.get("/public/courses")
def public_courses(tenant_id: str) -> list[dict]:
    """Unauthenticated list of a tenant's courses — for the signup dropdown."""
    service = get_service_client()
    return (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", tenant_id)
        .order("name")
        .execute()
        .data
        or []
    )


@router.get("/courses")
def list_courses(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff can list courses.",
        )
    service = get_service_client()
    courses = (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", profile.tenant_id)
        .order("name")
        .execute()
        .data
        or []
    )
    if profile.role == "teacher":
        enrolled = (
            service.table("enrollments")
            .select("course_id")
            .eq("profile_id", profile.user_id)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        )
        allowed = {e["course_id"] for e in enrolled}
        courses = [c for c in courses if c["id"] in allowed]
    for course in courses:
        course["subjects"] = _subjects_for(service, course["id"], profile.tenant_id)
    return courses


class CourseCreate(BaseModel):
    name: str


class SubjectCreate(BaseModel):
    course_id: str
    name: str


@router.post("/courses")
def create_course(
    body: CourseCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Course name is required.")
    service = get_service_client()
    row = (
        service.table("courses")
        .insert({"tenant_id": profile.tenant_id, "name": name})
        .execute()
        .data[0]
    )
    return {**row, "subjects": []}


@router.post("/subjects")
def create_subject(
    body: SubjectCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Subject name is required.")
    service = get_service_client()
    course = (
        service.table("courses")
        .select("id")
        .eq("id", body.course_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if course is None or not course.data:
        raise HTTPException(status_code=404, detail="Course not found.")
    return (
        service.table("subjects")
        .insert(
            {"tenant_id": profile.tenant_id, "course_id": body.course_id, "name": name}
        )
        .execute()
        .data[0]
    )


@router.delete("/courses/{course_id}")
def delete_course(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    try:
        service.table("courses").delete().eq("id", course_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail=f"Could not delete course (is it still in use?): {exc}",
        )
    return {"deleted": course_id}


@router.delete("/subjects/{subject_id}")
def delete_subject(
    subject_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    try:
        service.table("subjects").delete().eq("id", subject_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail=f"Could not delete subject (is it used by a quiz?): {exc}",
        )
    return {"deleted": subject_id}
