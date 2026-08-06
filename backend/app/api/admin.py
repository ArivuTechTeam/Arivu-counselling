"""
Admin API — institution-admin user management + analytics, and super-admin
platform analytics.

  GET    /api/v1/users          — institution's teachers + students
  POST   /api/v1/users          — admin creates a teacher/student (+ enroll)
  DELETE /api/v1/users/{id}      — admin removes a user
  GET    /api/v1/admin/stats     — this institution's counts
  GET    /api/v1/platform/stats  — super-admin: all institutions' counts
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1", tags=["admin"])

ADMIN_ROLES = {"institution_admin", "super_admin"}


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admins only.")


def _require_super(profile: CurrentProfile) -> None:
    if profile.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admins only.")


def _count(service, table: str, tenant_id: str, **filters) -> int:
    q = service.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in filters.items():
        q = q.eq(k, v)
    return len(q.execute().data or [])


# ── Users ───────────────────────────────────────────────────────────────────
@router.get("/users")
def list_users(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    _require_admin(profile)
    service = get_service_client()

    profiles = (
        service.table("profiles")
        .select("id, full_name, role")
        .eq("tenant_id", profile.tenant_id)
        .in_("role", ["teacher", "student"])
        .execute()
        .data
        or []
    )
    auth_users = service.auth.admin.list_users()
    auth_users = getattr(auth_users, "users", auth_users)
    email_by_id = {u.id: getattr(u, "email", None) for u in auth_users}

    enrollments = (
        service.table("enrollments")
        .select("profile_id, course_id")
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    courses = (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    course_name = {c["id"]: c["name"] for c in courses}
    courses_by_profile: dict[str, list[str]] = {}
    for e in enrollments:
        courses_by_profile.setdefault(e["profile_id"], []).append(
            course_name.get(e["course_id"], "?")
        )

    return [
        {
            "id": p["id"],
            "full_name": p["full_name"],
            "role": p["role"],
            "email": email_by_id.get(p["id"]),
            "courses": courses_by_profile.get(p["id"], []),
        }
        for p in profiles
    ]


class UserCreate(BaseModel):
    full_name: str
    email: str
    password: str
    role: Literal["teacher", "student"]
    course_id: str | None = None


@router.post("/users")
def create_user(
    body: UserCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    service = get_service_client()

    meta: dict = {
        "tenant_id": profile.tenant_id,
        "role": body.role,
        "full_name": body.full_name.strip(),
    }
    if body.course_id:
        meta["course_id"] = body.course_id

    try:
        created = service.auth.admin.create_user(
            {
                "email": body.email.strip(),
                "password": body.password,
                "email_confirm": True,  # admin-created accounts are ready to use
                "user_metadata": meta,
            }
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not create user: {exc}")

    return {"id": created.user.id, "email": body.email}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    # Only allow deleting a user inside the admin's own tenant.
    target = (
        service.table("profiles")
        .select("id")
        .eq("id", user_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if target is None or not target.data:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        service.auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not delete user: {exc}")
    return {"deleted": user_id}


# ── Analytics ────────────────────────────────────────────────────────────────
@router.get("/admin/stats")
def institution_stats(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    t = profile.tenant_id
    return {
        "teachers": _count(service, "profiles", t, role="teacher"),
        "students": _count(service, "profiles", t, role="student"),
        "courses": _count(service, "courses", t),
        "subjects": _count(service, "subjects", t),
        "quiz_sets": _count(service, "quiz_sets", t),
        "published_quizzes": _count(service, "quiz_sets", t, status="published"),
    }


@router.get("/platform/stats")
def platform_stats(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    _require_super(profile)
    service = get_service_client()

    tenants = (
        service.table("tenants").select("id, name").order("name").execute().data or []
    )
    all_profiles = (
        service.table("profiles").select("tenant_id, role").execute().data or []
    )

    per_tenant = []
    total_teachers = total_students = 0
    for ten in tenants:
        teachers = sum(
            1 for p in all_profiles if p["tenant_id"] == ten["id"] and p["role"] == "teacher"
        )
        students = sum(
            1 for p in all_profiles if p["tenant_id"] == ten["id"] and p["role"] == "student"
        )
        total_teachers += teachers
        total_students += students
        per_tenant.append(
            {"id": ten["id"], "name": ten["name"], "teachers": teachers, "students": students}
        )

    return {
        "institutions": len(tenants),
        "total_teachers": total_teachers,
        "total_students": total_students,
        "per_institution": per_tenant,
    }
