"""
Admin API — institution-admin user management + analytics, and super-admin
platform analytics.

  GET    /api/v1/users          — institution's teachers
  POST   /api/v1/users          — admin creates a teacher
  PUT    /api/v1/users/{id}     — admin edits a teacher and assignments
  POST   /api/v1/users/{id}/temporary-password — reset and copy a login
  DELETE /api/v1/users/{id}     — admin removes a teacher
  GET    /api/v1/teachers/{id}/courses — a teacher's assigned courses
  GET    /api/v1/courses/{id}/students — students enrolled in a course
  GET    /api/v1/admin/stats     — this institution's counts
  GET    /api/v1/platform/stats  — super-admin: all institutions' counts
"""

from __future__ import annotations

import secrets
import string
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.teacher_access import replace_teacher_subjects

router = APIRouter(prefix="/api/v1", tags=["admin"])

AUTH_USERS_PAGE_SIZE = 1000


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role != "institution_admin":
        raise HTTPException(status_code=403, detail="Institution admins only.")


def _require_super(profile: CurrentProfile) -> None:
    if profile.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admins only.")


def _count(service, table: str, tenant_id: str, **filters) -> int:
    q = service.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in filters.items():
        q = q.eq(k, v)
    return len(q.execute().data or [])


def _delete_auth_user_quietly(service, user_id: str) -> None:
    """Best-effort compensation for a failed multi-step provisioning flow."""
    try:
        service.auth.admin.delete_user(user_id)
    except Exception:  # noqa: BLE001
        pass


def _list_all_auth_users(service, *, per_page: int = AUTH_USERS_PAGE_SIZE) -> list:
    """Fetch every GoTrue user instead of silently stopping at its first page."""
    users: list = []
    page = 1
    while True:
        response = service.auth.admin.list_users(page=page, per_page=per_page)
        page_users = getattr(response, "users", response) or []
        page_users = list(page_users)
        users.extend(page_users)
        if len(page_users) < per_page:
            return users
        page += 1


def _email_by_auth_user_id(service) -> dict[str, str | None]:
    return {
        str(user.id): getattr(user, "email", None)
        for user in _list_all_auth_users(service)
    }


def _set_provisioned_profile(
    service, *, user_id: str, tenant_id: str, role: str, full_name: str
) -> None:
    updated = (
        service.table("profiles")
        .update(
            {
                "tenant_id": tenant_id,
                "role": role,
                "full_name": full_name.strip(),
            }
        )
        .eq("id", user_id)
        .execute()
    )
    if not updated.data:
        raise RuntimeError("The authorization profile was not created.")
    # Migration 11 makes this authoritative. Keep provisioning compatible
    # during a rolling deployment where API code may start just before DDL.
    try:
        service.table("profiles").update({"must_change_password": True}).eq(
            "id", user_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        if "must_change_password" not in str(exc):
            raise


# ── Institution teacher management ──────────────────────────────────────────
@router.get("/users")
def list_users(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    """List teachers managed by this institution admin.

    Student accounts are created through self-signup and deliberately excluded
    from this management endpoint.
    """
    _require_admin(profile)
    service = get_service_client()

    teachers = (
        service.table("profiles")
        .select("id, full_name, role, created_at")
        .eq("tenant_id", profile.tenant_id)
        .eq("role", "teacher")
        .execute()
        .data
        or []
    )
    email_by_id = _email_by_auth_user_id(service)

    assignments = (
        service.table("teacher_subjects")
        .select("teacher_id, subject_id")
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    subject_ids = list({str(row["subject_id"]) for row in assignments})
    subjects = []
    if subject_ids:
        subjects = (
            service.table("subjects")
            .select("id, course_id")
            .eq("tenant_id", profile.tenant_id)
            .in_("id", subject_ids)
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
    course_name = {str(course["id"]): course["name"] for course in courses}
    course_by_subject = {
        str(subject["id"]): str(subject["course_id"]) for subject in subjects
    }
    subjects_by_teacher: dict[str, set[str]] = {}
    course_ids_by_teacher: dict[str, set[str]] = {}
    for assignment in assignments:
        teacher_id = str(assignment["teacher_id"])
        subject_id = str(assignment["subject_id"])
        subjects_by_teacher.setdefault(teacher_id, set()).add(subject_id)
        course_id = course_by_subject.get(subject_id)
        if course_id:
            course_ids_by_teacher.setdefault(teacher_id, set()).add(course_id)

    teachers.sort(key=lambda teacher: teacher.get("created_at") or "", reverse=True)
    return [
        {
            "id": teacher["id"],
            "full_name": teacher["full_name"],
            "role": teacher["role"],
            "email": email_by_id.get(teacher["id"]),
            "courses": sorted(
                course_name[course_id]
                for course_id in course_ids_by_teacher.get(str(teacher["id"]), set())
                if course_id in course_name
            ),
            "subject_count": len(
                subjects_by_teacher.get(str(teacher["id"]), set())
            ),
            "created_at": teacher.get("created_at"),
        }
        for teacher in teachers
    ]


class TeacherCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str
    password: str
    course_id: str
    subject_ids: list[str] = Field(min_length=1, max_length=500)


class TeacherUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str
    subject_ids: list[str] = Field(max_length=500)


def _validated_subject_ids(
    service,
    *,
    tenant_id: str,
    subject_ids: list[str],
    course_id: str | None = None,
    require_subject: bool = True,
) -> list[str]:
    """Validate every assignment against the admin's tenant and optional course."""
    unique_ids = list(dict.fromkeys(str(subject_id) for subject_id in subject_ids))
    if not unique_ids and require_subject:
        raise HTTPException(status_code=400, detail="Select at least one subject.")
    if not unique_ids:
        return []

    if course_id is not None:
        course = (
            service.table("courses")
            .select("id")
            .eq("id", course_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if course is None or not course.data:
            raise HTTPException(status_code=400, detail="Course not found.")

    subjects = (
        service.table("subjects")
        .select("id, course_id")
        .eq("tenant_id", tenant_id)
        .in_("id", unique_ids)
        .execute()
        .data
        or []
    )
    if {str(subject["id"]) for subject in subjects} != set(unique_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more subjects do not belong to this institution.",
        )
    if course_id is not None and any(
        str(subject["course_id"]) != course_id for subject in subjects
    ):
        raise HTTPException(
            status_code=400,
            detail="Every selected subject must belong to the selected course.",
        )
    return unique_ids


def _tenant_course_exists(service, tenant_id: str, course_id: str) -> str:
    course = (
        service.table("courses")
        .select("id")
        .eq("id", course_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if course is None or not course.data:
        raise HTTPException(
            status_code=400,
            detail="Course not found.",
        )
    return str(course.data["id"])


@router.post("/users")
def create_user(
    body: TeacherCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Create a teacher; students join through the public signup flow."""
    _require_admin(profile)
    service = get_service_client()

    if not body.full_name.strip():
        raise HTTPException(status_code=400, detail="Full name is required.")
    provisioning_course_id = _tenant_course_exists(
        service, profile.tenant_id, body.course_id
    )
    subject_ids = _validated_subject_ids(
        service,
        tenant_id=profile.tenant_id,
        course_id=provisioning_course_id,
        subject_ids=body.subject_ids,
    )

    meta: dict = {
        "tenant_id": profile.tenant_id,
        "role": "teacher",
        "full_name": body.full_name.strip(),
        # Admin set a temp password → prompt them to change it on first login.
        "must_change_password": True,
        "course_id": provisioning_course_id,
    }

    try:
        created = service.auth.admin.create_user(
            {
                "email": body.email.strip(),
                "password": body.password,
                "email_confirm": True,  # admin-created accounts are ready to use
                "app_metadata": {"provisioned_by_backend": True},
                "user_metadata": meta,
            }
        )
        _set_provisioned_profile(
            service,
            user_id=created.user.id,
            tenant_id=profile.tenant_id,
            role="teacher",
            full_name=body.full_name,
        )
        replace_teacher_subjects(
            service,
            tenant_id=profile.tenant_id,
            teacher_id=created.user.id,
            subject_ids=subject_ids,
        )
    except Exception as exc:  # noqa: BLE001
        if "created" in locals() and created.user:
            _delete_auth_user_quietly(service, created.user.id)
        raise HTTPException(status_code=400, detail=f"Could not create user: {exc}")

    return {"id": created.user.id, "email": body.email.strip()}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
    service = get_service_client()
    # Only allow deleting a teacher inside the admin's own tenant.
    target = (
        service.table("profiles")
        .select("id, role")
        .eq("id", user_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if target is None or not target.data:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.data["role"] != "teacher":
        raise HTTPException(status_code=400, detail="Only teachers can be removed here.")
    if user_id == profile.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account.")
    try:
        service.auth.admin.delete_user(user_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail="Could not remove teacher. Their academic records were preserved.",
        )
    return {"deleted": user_id}


def _assert_tenant_teacher(service, *, teacher_id: str, tenant_id: str) -> dict:
    teacher = (
        service.table("profiles")
        .select("id, full_name")
        .eq("id", teacher_id)
        .eq("tenant_id", tenant_id)
        .eq("role", "teacher")
        .maybe_single()
        .execute()
    )
    if teacher is None or not teacher.data:
        raise HTTPException(status_code=404, detail="Teacher not found.")
    return teacher.data


def _generate_temporary_password(length: int = 14) -> str:
    """Create a strong temporary password without storing it in plaintext."""
    groups = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "!@#$%")
    characters = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    characters.extend(secrets.choice(alphabet) for _ in range(length - len(groups)))
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


@router.post("/users/{user_id}/temporary-password")
def reset_teacher_temporary_password(
    user_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Reset a tenant teacher's password and return it once for immediate copying."""
    _require_admin(profile)
    service = get_service_client()
    _assert_tenant_teacher(
        service, teacher_id=user_id, tenant_id=profile.tenant_id
    )
    temporary_password = _generate_temporary_password()
    try:
        updated_profile = (
            service.table("profiles")
            .update({"must_change_password": True})
            .eq("id", user_id)
            .eq("tenant_id", profile.tenant_id)
            .eq("role", "teacher")
            .execute()
        )
        if not updated_profile.data:
            raise RuntimeError("The teacher profile could not be updated.")
        auth_response = service.auth.admin.update_user_by_id(
            user_id, {"password": temporary_password}
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail="Could not generate a new temporary teacher login.",
        )
    auth_user = getattr(auth_response, "user", auth_response)
    return {
        "email": getattr(auth_user, "email", None),
        "password": temporary_password,
    }


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    body: TeacherUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Update a tenant teacher's identity and subject/course assignments."""
    _require_admin(profile)
    service = get_service_client()
    existing_profile = _assert_tenant_teacher(
        service, teacher_id=user_id, tenant_id=profile.tenant_id
    )
    full_name = body.full_name.strip()
    email = body.email.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Full name is required.")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required.")
    subject_ids = _validated_subject_ids(
        service,
        tenant_id=profile.tenant_id,
        subject_ids=body.subject_ids,
        require_subject=False,
    )
    previous_assignments = (
        service.table("teacher_subjects")
        .select("subject_id")
        .eq("teacher_id", user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    previous_subject_ids = [str(row["subject_id"]) for row in previous_assignments]

    try:
        auth_response = service.auth.admin.get_user_by_id(user_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail="Could not load the teacher's sign-in account.",
        )
    auth_user = getattr(auth_response, "user", auth_response)
    previous_email = getattr(auth_user, "email", None)
    previous_metadata = dict(getattr(auth_user, "user_metadata", None) or {})
    updated_metadata = {**previous_metadata, "full_name": full_name}

    auth_updated = False
    profile_updated = False
    try:
        service.auth.admin.update_user_by_id(
            user_id,
            {
                "email": email,
                "email_confirm": True,
                "user_metadata": updated_metadata,
            },
        )
        auth_updated = True
        updated_profile = (
            service.table("profiles")
            .update({"full_name": full_name})
            .eq("id", user_id)
            .eq("tenant_id", profile.tenant_id)
            .eq("role", "teacher")
            .execute()
        )
        if not updated_profile.data:
            raise RuntimeError("The teacher profile could not be updated.")
        profile_updated = True
        assigned = replace_teacher_subjects(
            service,
            tenant_id=profile.tenant_id,
            teacher_id=user_id,
            subject_ids=subject_ids,
        )
    except Exception as exc:  # noqa: BLE001
        # Best-effort compensation keeps the three stores aligned if a later
        # step fails after Supabase Auth has already accepted the new email.
        if profile_updated:
            try:
                service.table("profiles").update(
                    {"full_name": existing_profile.get("full_name")}
                ).eq("id", user_id).eq("tenant_id", profile.tenant_id).eq(
                    "role", "teacher"
                ).execute()
            except Exception:  # noqa: BLE001
                pass
        if auth_updated:
            try:
                rollback_attributes: dict = {"user_metadata": previous_metadata}
                if previous_email:
                    rollback_attributes["email"] = previous_email
                    rollback_attributes["email_confirm"] = True
                service.auth.admin.update_user_by_id(user_id, rollback_attributes)
            except Exception:  # noqa: BLE001
                pass
        try:
            replace_teacher_subjects(
                service,
                tenant_id=profile.tenant_id,
                teacher_id=user_id,
                subject_ids=previous_subject_ids,
            )
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=400, detail=f"Could not update teacher: {exc}")

    return {
        "id": user_id,
        "full_name": full_name,
        "email": email,
        "subject_ids": assigned,
    }


def _assert_tenant_course(service, *, course_id: str, tenant_id: str) -> dict:
    course = (
        service.table("courses")
        .select("id, name")
        .eq("id", course_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if course is None or not course.data:
        raise HTTPException(status_code=404, detail="Course not found.")
    return course.data


@router.get("/teachers/{teacher_id}/courses")
def list_teacher_courses(
    teacher_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Return courses derived from a teacher's explicit subject assignments."""
    _require_admin(profile)
    service = get_service_client()
    _assert_tenant_teacher(
        service, teacher_id=teacher_id, tenant_id=profile.tenant_id
    )

    assignments = (
        service.table("teacher_subjects")
        .select("subject_id")
        .eq("teacher_id", teacher_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    subject_ids = list({str(row["subject_id"]) for row in assignments})
    if not subject_ids:
        return []

    subjects = (
        service.table("subjects")
        .select("id, name, course_id")
        .eq("tenant_id", profile.tenant_id)
        .in_("id", subject_ids)
        .execute()
        .data
        or []
    )
    course_ids = list({str(subject["course_id"]) for subject in subjects})
    if not course_ids:
        return []
    courses = (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", profile.tenant_id)
        .in_("id", course_ids)
        .execute()
        .data
        or []
    )

    enrollments = (
        service.table("enrollments")
        .select("profile_id, course_id")
        .eq("tenant_id", profile.tenant_id)
        .in_("course_id", course_ids)
        .execute()
        .data
        or []
    )
    enrolled_profile_ids = list(
        {str(enrollment["profile_id"]) for enrollment in enrollments}
    )
    student_ids: set[str] = set()
    if enrolled_profile_ids:
        students = (
            service.table("profiles")
            .select("id")
            .eq("tenant_id", profile.tenant_id)
            .eq("role", "student")
            .in_("id", enrolled_profile_ids)
            .execute()
            .data
            or []
        )
        student_ids = {str(student["id"]) for student in students}

    subjects_by_course: dict[str, list[dict]] = {}
    for subject in subjects:
        subjects_by_course.setdefault(str(subject["course_id"]), []).append(
            {"id": str(subject["id"]), "name": subject["name"]}
        )
    student_count_by_course: dict[str, int] = {}
    for enrollment in enrollments:
        if str(enrollment["profile_id"]) in student_ids:
            course_id = str(enrollment["course_id"])
            student_count_by_course[course_id] = (
                student_count_by_course.get(course_id, 0) + 1
            )

    return sorted(
        [
            {
                "id": str(course["id"]),
                "name": course["name"],
                "subjects": sorted(
                    subjects_by_course.get(str(course["id"]), []),
                    key=lambda subject: subject["name"].lower(),
                ),
                "student_count": student_count_by_course.get(str(course["id"]), 0),
            }
            for course in courses
        ],
        key=lambda course: course["name"].lower(),
    )


@router.get("/courses/{course_id}/students")
def list_course_students(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Return the tenant-scoped student roster for one course."""
    _require_admin(profile)
    service = get_service_client()
    course = _assert_tenant_course(
        service, course_id=course_id, tenant_id=profile.tenant_id
    )
    enrollments = (
        service.table("enrollments")
        .select("profile_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("course_id", course_id)
        .execute()
        .data
        or []
    )
    profile_ids = list({str(row["profile_id"]) for row in enrollments})
    students = []
    if profile_ids:
        students = (
            service.table("profiles")
            .select("id, full_name")
            .eq("tenant_id", profile.tenant_id)
            .eq("role", "student")
            .in_("id", profile_ids)
            .execute()
            .data
            or []
        )
    email_by_id = _email_by_auth_user_id(service) if students else {}
    roster = sorted(
        [
            {
                "id": str(student["id"]),
                "full_name": student["full_name"],
                "email": email_by_id.get(str(student["id"])),
            }
            for student in students
        ],
        key=lambda student: (student["full_name"] or student["email"] or "").lower(),
    )
    return {
        "course": {"id": str(course["id"]), "name": course["name"]},
        "count": len(roster),
        "students": roster,
    }


# ── Super-admin: institution admins ──────────────────────────────────────────
class AdminCreate(BaseModel):
    full_name: str
    email: str
    password: str
    tenant_id: str


@router.get("/tenants")
def list_tenants(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Institutions (tenants) the super-admin can assign an admin to."""
    _require_super(profile)
    service = get_service_client()
    return (
        service.table("tenants").select("id, name").order("name").execute().data or []
    )


@router.get("/admins")
def list_admins(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Every institution admin across the platform, with their institution."""
    _require_super(profile)
    service = get_service_client()
    admins = (
        service.table("profiles")
        .select("id, full_name, tenant_id")
        .eq("role", "institution_admin")
        .execute()
        .data
        or []
    )
    email_by_id = _email_by_auth_user_id(service)
    tenants = service.table("tenants").select("id, name").execute().data or []
    tname = {t["id"]: t["name"] for t in tenants}
    return [
        {
            "id": a["id"],
            "full_name": a["full_name"],
            "email": email_by_id.get(a["id"]),
            "institution": tname.get(a["tenant_id"], "?"),
        }
        for a in admins
    ]


@router.post("/admins")
def create_admin(
    body: AdminCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin creates an institution admin (aka principal) for a tenant."""
    _require_super(profile)
    service = get_service_client()

    tenant = (
        service.table("tenants")
        .select("id")
        .eq("id", body.tenant_id)
        .maybe_single()
        .execute()
    )
    if tenant is None or not tenant.data:
        raise HTTPException(status_code=400, detail="Institution not found.")

    try:
        created = service.auth.admin.create_user(
            {
                "email": body.email.strip(),
                "password": body.password,
                "email_confirm": True,  # ready to sign in immediately
                "app_metadata": {"provisioned_by_backend": True},
                "user_metadata": {
                    "tenant_id": body.tenant_id,
                    "role": "institution_admin",
                    "full_name": body.full_name.strip(),
                    "must_change_password": True,
                },
            }
        )
        _set_provisioned_profile(
            service,
            user_id=created.user.id,
            tenant_id=body.tenant_id,
            role="institution_admin",
            full_name=body.full_name,
        )
    except Exception as exc:  # noqa: BLE001
        if "created" in locals() and created.user:
            _delete_auth_user_quietly(service, created.user.id)
        raise HTTPException(status_code=400, detail=f"Could not create admin: {exc}")

    return {"id": created.user.id, "email": body.email}


@router.delete("/platform/admins/{user_id}")
def remove_admin(
    user_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin removes an institution admin (auth user + profile)."""
    _require_super(profile)
    service = get_service_client()

    target = (
        service.table("profiles")
        .select("id, role")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if target is None or not target.data:
        raise HTTPException(status_code=404, detail="Admin not found.")
    if target.data["role"] != "institution_admin":
        raise HTTPException(status_code=400, detail="That user is not an institution admin.")
    if user_id == profile.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove your own account.")

    # Delete the auth user first (source of truth); then clear the profile row in
    # case the FK isn't set to cascade.
    try:
        service.auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not remove admin: {exc}")
    service.table("profiles").delete().eq("id", user_id).execute()

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


@router.get("/admin/overview")
def institution_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Rich, real-data overview for the institution-admin dashboard: people counts,
    content counts, institution-wide accuracy, a 14-day activity trend, top
    courses by enrolment, the question review pipeline, and recent quiz sets.
    """
    from collections import Counter
    from datetime import date, timedelta

    _require_admin(profile)
    service = get_service_client()
    t = profile.tenant_id

    # Fetch through the shared helper so database failures are surfaced rather
    # than converted into valid-looking zero metrics.
    data = _gather(
        {
            "profiles": lambda: service.table("profiles")
            .select("role")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "courses": lambda: service.table("courses")
            .select("id, name")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "subjects": lambda: service.table("subjects")
            .select("id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "documents": lambda: service.table("documents")
            .select("id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "quiz_sets": lambda: service.table("quiz_sets")
            .select("id, title, status, created_at")
            .eq("tenant_id", t)
            .order("created_at", desc=True)
            .execute()
            .data
            or [],
            "questions": lambda: service.table("questions")
            .select("review_status")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "variants": lambda: service.table("quiz_variants")
            .select("id, total_marks")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "attempts": lambda: service.table("quiz_attempts")
            .select("status, total_score, variant_id, submitted_at")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "enrollments": lambda: service.table("enrollments")
            .select("course_id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
        }
    )

    # People
    profiles = data["profiles"]
    roles = Counter(p["role"] for p in profiles)

    # Content counts
    courses_rows = data["courses"]
    course_name = {c["id"]: c["name"] for c in courses_rows}
    subjects = len(data["subjects"])
    documents = len(data["documents"])

    quiz_sets = data["quiz_sets"]
    published = sum(1 for q in quiz_sets if q["status"] == "published")
    draft = sum(1 for q in quiz_sets if q["status"] == "draft")

    # Question review pipeline
    questions = data["questions"]
    pipeline = {"pending_review": 0, "approved": 0, "rejected": 0}
    for q in questions:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    # Attempts -> institution accuracy + activity trend
    variants = data["variants"]
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    attempts = data["attempts"]
    graded = [a for a in attempts if a["status"] == "graded"]
    pcts = []
    for a in graded:
        m = var_marks.get(a["variant_id"])
        if m:
            pcts.append(max(0, min(100, round((a.get("total_score") or 0) / m * 100))))
    accuracy = round(sum(pcts) / len(pcts)) if pcts else 0

    today = date.today()
    window = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    day_counts = {d.isoformat(): 0 for d in window}
    for a in graded:
        sa = a.get("submitted_at")
        if sa and sa[:10] in day_counts:
            day_counts[sa[:10]] += 1
    activity = [{"date": d.isoformat()[5:], "attempts": day_counts[d.isoformat()]} for d in window]

    # Top courses by enrolment
    enrollments = data["enrollments"]
    enr_counts = Counter(e["course_id"] for e in enrollments)
    top_courses = sorted(
        [
            {"name": course_name.get(cid, "Course"), "students": n}
            for cid, n in enr_counts.items()
        ],
        key=lambda x: -x["students"],
    )[:5]

    recent_quiz_sets = [
        {"title": q["title"], "status": q["status"], "created_at": q.get("created_at")}
        for q in quiz_sets[:5]
    ]

    return {
        "teachers": roles.get("teacher", 0),
        "students": roles.get("student", 0),
        "admins": roles.get("institution_admin", 0),
        "courses": len(courses_rows),
        "subjects": subjects,
        "documents": documents,
        "quiz_sets": len(quiz_sets),
        "published_quizzes": published,
        "draft_quizzes": draft,
        "questions": len(questions),
        "attempts": len(attempts),
        "graded_attempts": len(graded),
        "accuracy": accuracy,
        "pipeline": pipeline,
        "activity": activity,
        "top_courses": top_courses,
        "recent_quiz_sets": recent_quiz_sets,
    }


# ── Institution admin: Analytics (data-analyst report, no AI) ────────────────
class AnalyticsFinding(BaseModel):
    severity: Literal["critical", "warn", "good", "info"]
    title: str
    detail: str
    action: str
    action_type: Literal["pending_review", "at_risk", "course", "teacher"] | None = None
    action_id: str | None = None
    action_label: str | None = None


class AtRiskQuiz(BaseModel):
    quiz_set_id: str
    title: str
    accuracy: int
    attempts: int
    last_attempted_at: datetime | None = None


class AtRiskStudent(BaseModel):
    student_id: str
    name: str
    accuracy: int
    attempts: int
    worst_quiz: AtRiskQuiz | None = None
    quizzes: list[AtRiskQuiz]


class AnalyticsSummary(BaseModel):
    students: int
    teachers: int
    active_week: int
    inactive_students: int
    at_risk: int
    avg_accuracy: int
    graded_attempts: int
    published_quizzes: int
    courses: int


class AnalyticsTrend(BaseModel):
    attempts_last7: int
    attempts_prev7: int
    delta: int
    has_trend: bool


class AnalyticsPipeline(BaseModel):
    pending_review: int
    approved: int
    rejected: int


class CoursePerformance(BaseModel):
    course_id: str
    name: str
    students: int
    published: int
    pending_review: int
    accuracy: int
    attempts: int


class TeacherPerformance(BaseModel):
    teacher_id: str
    name: str
    quiz_sets: int
    published: int
    approved: int
    attempts: int
    accuracy: int
    last_quiz_created: datetime | None = None
    is_active: bool


class AnalyticsActivity(BaseModel):
    date: str
    attempts: int


class InstitutionAnalyticsResponse(BaseModel):
    updated_at: datetime
    summary: AnalyticsSummary
    trend: AnalyticsTrend
    activity: list[AnalyticsActivity]
    pipeline: AnalyticsPipeline
    course_perf: list[CoursePerformance]
    teacher_activity: list[TeacherPerformance]
    at_risk_students: list[AtRiskStudent]
    findings: list[AnalyticsFinding]


def _gather(thunks: dict) -> dict:
    """Run Supabase reads sequentially and propagate failures to the UI.

    A sync client is not safe to share across worker threads; doing so
    caused intermittent HTTP/2 disconnects and false zero-value dashboards.
    """
    return {key: thunk() for key, thunk in thunks.items()}


def _admin_findings(
    *, summary: dict, trend: dict, pipeline: dict, course_perf: list, teacher_activity: list
) -> list[dict]:
    """Turn institution metrics into ranked, plain-language decisions (no AI)."""
    out: list[dict] = []
    n_students = summary["students"]

    if n_students == 0:
        out.append(
            {
                "severity": "info",
                "title": "No students enrolled yet",
                "detail": "Enroll students and assign quizzes to see engagement and "
                "outcomes here.",
                "action": "Add students under your courses.",
            }
        )
        return out

    # 1) Outcome verdict.
    if summary["graded_attempts"] > 0:
        acc = summary["avg_accuracy"]
        if acc >= 70:
            out.append(
                {
                    "severity": "good",
                    "title": f"Students are doing well — {acc}% average accuracy",
                    "detail": f"Across {summary['graded_attempts']} graded attempts.",
                    "action": "Consider harder quizzes to stretch your top students.",
                }
            )
        elif acc >= 40:
            out.append(
                {
                    "severity": "warn",
                    "title": f"Average accuracy is {acc}% — room to improve",
                    "detail": "Students are passing, but not comfortably.",
                    "action": "Ask teachers to revisit weak topics and add practice quizzes.",
                }
            )
        else:
            out.append(
                {
                    "severity": "critical",
                    "title": f"Low average accuracy — {acc}%",
                    "detail": "Students are struggling across the board.",
                    "action": "Check quiz difficulty and revisit the weak teaching material.",
                }
            )
    else:
        out.append(
            {
                "severity": "info",
                "title": "No graded attempts yet",
                "detail": "Once students take and submit quizzes, outcomes appear here.",
                "action": "Ask teachers to publish quizzes and students to attempt them.",
            }
        )

    # 2) Students who never attempted anything.
    inactive = summary["inactive_students"]
    if inactive and n_students:
        share = round(inactive / n_students * 100)
        if share >= 30:
            out.append(
                {
                    "severity": "warn",
                    "title": f"{share}% of students haven't taken any quiz",
                    "detail": f"{inactive} of {n_students} students have zero attempts.",
                    "action": "Ask teachers to assign or publish quizzes for them.",
                }
            )

    # 3) Struggling students.
    if summary["at_risk"] > 0:
        out.append(
            {
                "severity": "critical" if summary["at_risk"] >= 3 else "warn",
                "title": f"{summary['at_risk']} student(s) are struggling",
                "detail": "These students average below 40% — they may need extra help.",
                "action": "Open the at-risk list and review each student's weakest quiz.",
                "action_type": "at_risk",
                "action_label": "View students",
            }
        )

    # 4) Engagement trend.
    if trend["has_trend"] and (trend["attempts_last7"] + trend["attempts_prev7"]) >= 4:
        d = trend["delta"]
        if d < 0:
            out.append(
                {
                    "severity": "warn",
                    "title": f"Engagement dropped this week ({d} attempts)",
                    "detail": f"{trend['attempts_prev7']} attempts last week → "
                    f"{trend['attempts_last7']} this week.",
                    "action": "A fresh quiz or a reminder can bring students back.",
                }
            )
        elif d > 0:
            out.append(
                {
                    "severity": "good",
                    "title": f"Engagement is up (+{d} attempts this week)",
                    "detail": f"{trend['attempts_prev7']} → {trend['attempts_last7']} "
                    "attempts week-over-week.",
                    "action": "Keep the momentum with regular quizzes.",
                }
            )

    # 5) Courses with students but nothing to attempt.
    gaps = [c for c in course_perf if c["students"] > 0 and c["published"] == 0]
    if gaps:
        c = gaps[0]
        more = f" (+{len(gaps) - 1} more course)" if len(gaps) > 1 else ""
        out.append(
            {
                "severity": "warn",
                "title": f"{c['name']} has students but no published quiz",
                "detail": f"{c['students']} enrolled with nothing to attempt yet{more}.",
                "action": "Ask that course's teacher to publish a quiz.",
                "action_type": "course",
                "action_id": c["course_id"],
                "action_label": "View course",
            }
        )

    # 6) Review backlog.
    if pipeline["pending_review"] > 0:
        out.append(
            {
                "severity": "critical" if pipeline["pending_review"] >= 10 else "warn",
                "title": f"{pipeline['pending_review']} questions await review",
                "detail": "Unreviewed questions can't be published to students.",
                "action": "Nudge teachers to clear their review queue.",
                "action_type": "pending_review",
                "action_label": "View pending",
            }
        )

    # 7) Teachers creating content without publishing it.
    unpublished = [
        teacher
        for teacher in teacher_activity
        if teacher["quiz_sets"] > 0 and teacher["published"] == 0
    ]
    if unpublished:
        teacher = unpublished[0]
        out.append(
            {
                "severity": "warn",
                "title": f"{teacher['name']} has created quizzes but published none",
                "detail": f"{teacher['quiz_sets']} quiz set(s) are not available to students.",
                "action": "Review this teacher's drafts and help move ready quizzes to published.",
                "action_type": "teacher",
                "action_id": teacher["teacher_id"],
                "action_label": "View teacher",
            }
        )

    # 8) Courses with weak outcomes.
    weak_courses = [
        course
        for course in course_perf
        if course["attempts"] > 0 and course["accuracy"] < 50
    ]
    if weak_courses:
        course = min(weak_courses, key=lambda row: row["accuracy"])
        out.append(
            {
                "severity": "warn" if course["accuracy"] >= 40 else "critical",
                "title": f"{course['name']} is averaging {course['accuracy']}% accuracy",
                "detail": f"Based on {course['attempts']} graded attempt(s).",
                "action": "Open the course and inspect its lowest-performing quizzes.",
                "action_type": "course",
                "action_id": course["course_id"],
                "action_label": "View course",
            }
        )

    # 9) Idle teachers.
    idle = [t for t in teacher_activity if t["quiz_sets"] == 0]
    if idle and summary["teachers"]:
        out.append(
            {
                "severity": "info",
                "title": f"{len(idle)} teacher(s) haven't created a quiz",
                "detail": "Some teachers aren't using the platform yet.",
                "action": "Check whether they need onboarding help.",
                "action_type": "teacher",
                "action_id": idle[0]["teacher_id"],
                "action_label": "View teacher",
            }
        )

    severity_rank = {"critical": 0, "warn": 1, "good": 2, "info": 3}
    return sorted(out, key=lambda finding: severity_rank[finding["severity"]])


@router.get("/admin/analytics", response_model=InstitutionAnalyticsResponse)
def institution_analytics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> InstitutionAnalyticsResponse:
    """Data-analyst-style analytics for the institution admin: engagement, student
    outcomes, course performance, teacher activity, and plain-language findings.
    Pure database aggregation — no AI/ML."""
    from collections import Counter, defaultdict
    from datetime import date, datetime, timedelta

    _require_admin(profile)
    service = get_service_client()
    t = profile.tenant_id

    data = _gather(
        {
            "profiles": lambda: service.table("profiles")
            .select("id, role, full_name")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "courses": lambda: service.table("courses")
            .select("id, name")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "subjects": lambda: service.table("subjects")
            .select("id, course_id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "quiz_sets": lambda: service.table("quiz_sets")
            .select("id, title, status, created_by, subject_id, created_at")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "questions": lambda: service.table("questions")
            .select("id, review_status, source, type, reviewed_by")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "variant_questions": lambda: service.table("quiz_variant_questions")
            .select("variant_id, question_id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "variants": lambda: service.table("quiz_variants")
            .select("id, total_marks, quiz_set_id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "attempts": lambda: service.table("quiz_attempts")
            .select("student_id, status, total_score, variant_id, submitted_at")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
            "enrollments": lambda: service.table("enrollments")
            .select("profile_id, course_id")
            .eq("tenant_id", t)
            .execute()
            .data
            or [],
        }
    )
    profiles = data["profiles"]
    courses = data["courses"]
    subjects = data["subjects"]
    quiz_sets = data["quiz_sets"]
    questions = data["questions"]
    variant_questions = data["variant_questions"]
    variants = data["variants"]
    attempts = data["attempts"]
    enrollments = data["enrollments"]

    students = [p for p in profiles if p["role"] == "student"]
    teachers = [p for p in profiles if p["role"] == "teacher"]
    name_by_id = {p["id"]: (p.get("full_name") or "—") for p in profiles}

    # Lookups to walk attempt -> variant -> quiz set -> subject -> course.
    subject_course = {s["id"]: s.get("course_id") for s in subjects}
    course_name = {c["id"]: c["name"] for c in courses}
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    var_quizset = {v["id"]: v.get("quiz_set_id") for v in variants}
    quizset_course = {
        q["id"]: subject_course.get(q.get("subject_id")) for q in quiz_sets
    }

    today = date.today()
    current_week_start = (today - timedelta(days=6)).isoformat()
    previous_week_start = (today - timedelta(days=13)).isoformat()

    def pct(a: dict):
        m = var_marks.get(a["variant_id"])
        if not m:
            return None
        return max(0, min(100, (a.get("total_score") or 0) / m * 100))

    graded = [a for a in attempts if a["status"] == "graded"]
    stu_pcts: dict = defaultdict(list)
    course_pcts: dict = defaultdict(list)
    quizset_pcts: dict = defaultdict(list)
    quizset_scores: dict = defaultdict(lambda: [0.0, 0.0])
    course_scores: dict = defaultdict(lambda: [0.0, 0.0])
    student_scores: dict = defaultdict(lambda: [0.0, 0.0])
    student_quiz_pcts: dict = defaultdict(lambda: defaultdict(list))
    student_quiz_scores: dict = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0.0])
    )
    student_quiz_last: dict = defaultdict(dict)
    active_ids: set = set()
    attempts_last7 = attempts_prev7 = 0
    for a in graded:
        p = pct(a)
        sid = a.get("student_id")
        sa = a.get("submitted_at")
        if p is not None:
            max_score = float(var_marks[a["variant_id"]])
            score = max(0.0, min(max_score, float(a.get("total_score") or 0)))
            if sid:
                stu_pcts[sid].append(p)
                student_scores[sid][0] += score
                student_scores[sid][1] += max_score
            quiz_set_id = var_quizset.get(a["variant_id"])
            if quiz_set_id:
                quizset_pcts[quiz_set_id].append(p)
                quizset_scores[quiz_set_id][0] += score
                quizset_scores[quiz_set_id][1] += max_score
                if sid:
                    student_quiz_pcts[sid][quiz_set_id].append(p)
                    student_quiz_scores[sid][quiz_set_id][0] += score
                    student_quiz_scores[sid][quiz_set_id][1] += max_score
                    if sa and sa > student_quiz_last[sid].get(quiz_set_id, ""):
                        student_quiz_last[sid][quiz_set_id] = sa
            cid = quizset_course.get(quiz_set_id)
            if cid:
                course_pcts[cid].append(p)
                course_scores[cid][0] += score
                course_scores[cid][1] += max_score
        if sa:
            day = sa[:10]
            if current_week_start <= day <= today.isoformat():
                attempts_last7 += 1
                if sid:
                    active_ids.add(sid)
            elif previous_week_start <= day < current_week_start:
                attempts_prev7 += 1

    total_score = sum(value[0] for value in student_scores.values())
    total_possible = sum(value[1] for value in student_scores.values())
    avg_accuracy = round(total_score / total_possible * 100) if total_possible else 0
    with_attempts = set(stu_pcts.keys())
    inactive_students = [s for s in students if s["id"] not in with_attempts]

    quizset_title = {q["id"]: q.get("title") or "Untitled quiz" for q in quiz_sets}
    at_risk = []
    for s in students:
        ps = stu_pcts.get(s["id"])
        if ps:
            score, possible = student_scores[s["id"]]
            avg = score / possible * 100 if possible else 0
            if avg < 40:
                quiz_rows = sorted(
                    [
                        {
                            "quiz_set_id": quiz_set_id,
                            "title": quizset_title.get(quiz_set_id, "Untitled quiz"),
                            "accuracy": round(
                                student_quiz_scores[s["id"]][quiz_set_id][0]
                                / student_quiz_scores[s["id"]][quiz_set_id][1]
                                * 100
                            ),
                            "attempts": len(values),
                            "last_attempted_at": student_quiz_last[s["id"]].get(quiz_set_id),
                        }
                        for quiz_set_id, values in student_quiz_pcts[s["id"]].items()
                    ],
                    key=lambda row: (row["accuracy"], -row["attempts"]),
                )
                at_risk.append({
                    "student_id": s["id"],
                    "name": name_by_id.get(s["id"], "—"),
                    "accuracy": round(avg),
                    "attempts": len(ps),
                    "worst_quiz": quiz_rows[0] if quiz_rows else None,
                    "quizzes": quiz_rows,
                })
    at_risk.sort(key=lambda x: x["accuracy"])

    window = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    dc = {d.isoformat(): 0 for d in window}
    for a in graded:
        sa = a.get("submitted_at")
        if sa and sa[:10] in dc:
            dc[sa[:10]] += 1
    activity = [
        {"date": d.isoformat()[5:], "attempts": dc[d.isoformat()]} for d in window
    ]

    # Course performance.
    enr_by_course = Counter(e["course_id"] for e in enrollments)
    published_by_course = Counter(
        quizset_course.get(q["id"]) for q in quiz_sets if q["status"] == "published"
    )
    pending_question_ids = {
        q["id"] for q in questions if q.get("review_status") == "pending_review"
    }
    pending_by_course: dict[str, set[str]] = defaultdict(set)
    for link in variant_questions:
        question_id = link.get("question_id")
        quiz_set_id = var_quizset.get(link.get("variant_id"))
        course_id = quizset_course.get(quiz_set_id)
        if question_id in pending_question_ids and course_id:
            pending_by_course[course_id].add(question_id)
    course_perf = sorted(
        [
            {
                "course_id": c["id"],
                "name": course_name.get(c["id"], "Course"),
                "students": enr_by_course.get(c["id"], 0),
                "published": published_by_course.get(c["id"], 0),
                "pending_review": len(pending_by_course.get(c["id"], set())),
                "accuracy": (
                    round(course_scores[c["id"]][0] / course_scores[c["id"]][1] * 100)
                    if course_scores.get(c["id"], [0, 0])[1]
                    else 0
                ),
                "attempts": len(course_pcts.get(c["id"], [])),
            }
            for c in courses
        ],
        key=lambda x: -x["students"],
    )

    # Teacher activity.
    qs_by_teacher: dict = defaultdict(
        lambda: {"sets": 0, "published": 0, "last_quiz_created": None}
    )
    for q in quiz_sets:
        b = qs_by_teacher[q.get("created_by")]
        b["sets"] += 1
        created_at = q.get("created_at")
        if created_at and (
            b["last_quiz_created"] is None or created_at > b["last_quiz_created"]
        ):
            b["last_quiz_created"] = created_at
        if q["status"] == "published":
            b["published"] += 1
    approved_by_teacher = Counter(
        q.get("reviewed_by")
        for q in questions
        if q.get("review_status") == "approved" and q.get("reviewed_by")
    )
    teacher_pcts: dict = defaultdict(list)
    teacher_scores: dict = defaultdict(lambda: [0.0, 0.0])
    for quiz_set in quiz_sets:
        teacher_id = quiz_set.get("created_by")
        if teacher_id:
            teacher_pcts[teacher_id].extend(quizset_pcts.get(quiz_set["id"], []))
            teacher_scores[teacher_id][0] += quizset_scores[quiz_set["id"]][0]
            teacher_scores[teacher_id][1] += quizset_scores[quiz_set["id"]][1]
    teacher_activity = sorted(
        [
            {
                "teacher_id": tt["id"],
                "name": tt.get("full_name") or "—",
                "quiz_sets": qs_by_teacher.get(tt["id"], {}).get("sets", 0),
                "published": qs_by_teacher.get(tt["id"], {}).get("published", 0),
                "approved": approved_by_teacher.get(tt["id"], 0),
                "attempts": len(teacher_pcts.get(tt["id"], [])),
                "accuracy": (
                    round(
                        teacher_scores[tt["id"]][0]
                        / teacher_scores[tt["id"]][1]
                        * 100
                    )
                    if teacher_pcts.get(tt["id"])
                    else 0
                ),
                "last_quiz_created": qs_by_teacher.get(tt["id"], {}).get(
                    "last_quiz_created"
                ),
                "is_active": qs_by_teacher.get(tt["id"], {}).get("sets", 0) > 0,
            }
            for tt in teachers
        ],
        key=lambda x: (-x["attempts"], -x["quiz_sets"], x["name"].lower()),
    )

    pipeline = {"pending_review": 0, "approved": 0, "rejected": 0}
    for q in questions:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    trend = {
        "attempts_last7": attempts_last7,
        "attempts_prev7": attempts_prev7,
        "delta": attempts_last7 - attempts_prev7,
        "has_trend": (attempts_last7 + attempts_prev7) > 0,
    }
    summary = {
        "students": len(students),
        "teachers": len(teachers),
        "active_week": len(active_ids),
        "inactive_students": len(inactive_students),
        "at_risk": len(at_risk),
        "avg_accuracy": avg_accuracy,
        "graded_attempts": len(graded),
        "published_quizzes": sum(1 for q in quiz_sets if q["status"] == "published"),
        "courses": len(courses),
    }

    return InstitutionAnalyticsResponse(**{
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "trend": trend,
        "activity": activity,
        "pipeline": pipeline,
        "course_perf": course_perf,
        "teacher_activity": teacher_activity,
        "at_risk_students": at_risk,
        "findings": _admin_findings(
            summary=summary,
            trend=trend,
            pipeline=pipeline,
            course_perf=course_perf,
            teacher_activity=teacher_activity,
        ),
    })


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


@router.get("/platform/overview")
def platform_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Cross-tenant command-center overview for the super admin: platform-wide
    people/content counts, question approval rate (the ≥70% quality KPI),
    platform accuracy, a 14-day activity trend, and a per-institution table
    with each institution's key numbers + health. All real data.
    """
    from collections import Counter, defaultdict
    from datetime import date, timedelta

    _require_super(profile)
    service = get_service_client()

    tenants = (
        service.table("tenants")
        .select("id, name, subdomain, plan_tier, is_active, created_at")
        .order("name")
        .execute()
        .data
        or []
    )

    profiles = (
        service.table("profiles").select("tenant_id, role").execute().data or []
    )
    quiz_sets = (
        service.table("quiz_sets").select("tenant_id, status").execute().data or []
    )
    questions = (
        service.table("questions").select("tenant_id, review_status").execute().data or []
    )
    variants = (
        service.table("quiz_variants").select("id, tenant_id, total_marks").execute().data or []
    )
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    attempts = (
        service.table("quiz_attempts")
        .select("tenant_id, status, total_score, variant_id, submitted_at")
        .execute()
        .data
        or []
    )
    documents = service.table("documents").select("tenant_id").execute().data or []

    # ---- Per-tenant aggregation -------------------------------------------
    def blank() -> dict:
        return {
            "teachers": 0,
            "students": 0,
            "admins": 0,
            "quiz_sets": 0,
            "published": 0,
            "attempts": 0,
            "acc_sum": 0,
            "acc_n": 0,
        }

    agg: dict = defaultdict(blank)
    for p in profiles:
        a = agg[p["tenant_id"]]
        if p["role"] == "teacher":
            a["teachers"] += 1
        elif p["role"] == "student":
            a["students"] += 1
        elif p["role"] == "institution_admin":
            a["admins"] += 1
    for q in quiz_sets:
        a = agg[q["tenant_id"]]
        a["quiz_sets"] += 1
        if q["status"] == "published":
            a["published"] += 1

    graded_pcts: list[int] = []
    for at in attempts:
        a = agg[at["tenant_id"]]
        if at["status"] != "graded":
            continue
        a["attempts"] += 1
        m = var_marks.get(at["variant_id"])
        if m:
            pct = max(0, min(100, round((at.get("total_score") or 0) / m * 100)))
            a["acc_sum"] += pct
            a["acc_n"] += 1
            graded_pcts.append(pct)

    institutions = []
    for t in tenants:
        a = agg.get(t["id"], blank())
        acc = round(a["acc_sum"] / a["acc_n"]) if a["acc_n"] else 0
        institutions.append(
            {
                "id": t["id"],
                "name": t["name"],
                "subdomain": t.get("subdomain"),
                "created_at": t.get("created_at"),
                "plan_tier": t.get("plan_tier"),
                "is_active": t.get("is_active", True),
                "teachers": a["teachers"],
                "students": a["students"],
                "admins": a["admins"],
                "quiz_sets": a["quiz_sets"],
                "published": a["published"],
                "attempts": a["attempts"],
                "accuracy": acc,
            }
        )
    institutions.sort(key=lambda x: -(x["students"] + x["teachers"]))

    # ---- Question approval rate (the ≥70% quality KPI) --------------------
    q_status = Counter(q.get("review_status") for q in questions)
    decided = (
        q_status.get("approved", 0)
        + q_status.get("rejected", 0)
        + q_status.get("needs_edit", 0)
    )
    approval_rate = round(q_status.get("approved", 0) / decided * 100) if decided else 0

    # ---- 14-day platform activity (graded attempts across all tenants) ----
    today = date.today()
    window = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    day_counts = {d.isoformat(): 0 for d in window}
    for at in attempts:
        if at["status"] != "graded":
            continue
        sa = at.get("submitted_at")
        if sa and sa[:10] in day_counts:
            day_counts[sa[:10]] += 1
    activity = [{"date": d.isoformat()[5:], "attempts": day_counts[d.isoformat()]} for d in window]

    roles = Counter(p["role"] for p in profiles)
    return {
        "institutions": len(tenants),
        "active_institutions": sum(1 for t in tenants if t.get("is_active", True)),
        "teachers": roles.get("teacher", 0),
        "students": roles.get("student", 0),
        "admins": roles.get("institution_admin", 0),
        "quiz_sets": len(quiz_sets),
        "published_quizzes": sum(1 for q in quiz_sets if q["status"] == "published"),
        "questions": len(questions),
        "documents": len(documents),
        "attempts": sum(1 for a in attempts if a["status"] == "graded"),
        "accuracy": round(sum(graded_pcts) / len(graded_pcts)) if graded_pcts else 0,
        "approval_rate": approval_rate,
        "pipeline": {
            "pending_review": q_status.get("pending_review", 0),
            "approved": q_status.get("approved", 0),
            "rejected": q_status.get("rejected", 0),
            "needs_edit": q_status.get("needs_edit", 0),
        },
        "activity": activity,
        "institutions_table": institutions,
    }


# ── Super-admin: onboard a new institution (tenant) ──────────────────────────
class TenantCreate(BaseModel):
    name: str
    subdomain: str
    plan_tier: Literal["free", "starter", "growth", "enterprise"] = "free"
    # Optional first institution admin created alongside the tenant.
    admin_full_name: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None


@router.post("/platform/tenants")
def onboard_institution(
    body: TenantCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin onboards a new institution (Stage 1 of the workflow)."""
    _require_super(profile)
    service = get_service_client()

    name = body.name.strip()
    subdomain = body.subdomain.strip().lower()
    if not name or not subdomain:
        raise HTTPException(status_code=400, detail="Name and subdomain are required.")
    supplied_admin_fields = [
        body.admin_full_name,
        body.admin_email,
        body.admin_password,
    ]
    if any(supplied_admin_fields) and not all(supplied_admin_fields):
        raise HTTPException(
            status_code=400,
            detail="Admin name, email and temporary password are all required together.",
        )
    if not all(c.isalnum() or c == "-" for c in subdomain):
        raise HTTPException(
            status_code=400,
            detail="Subdomain may only contain letters, numbers, and hyphens.",
        )
    taken = (
        service.table("tenants").select("id").eq("subdomain", subdomain).execute().data
        or []
    )
    if taken:
        raise HTTPException(status_code=400, detail="That subdomain is already taken.")

    try:
        created = (
            service.table("tenants")
            .insert(
                {
                    "name": name,
                    "subdomain": subdomain,
                    "plan_tier": body.plan_tier,
                    "is_active": True,
                }
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not create institution: {exc}")
    tenant_id = created.data[0]["id"]

    admin = None
    if body.admin_email and body.admin_password:
        try:
            u = service.auth.admin.create_user(
                {
                    "email": body.admin_email.strip(),
                    "password": body.admin_password,
                    "email_confirm": True,
                    "app_metadata": {"provisioned_by_backend": True},
                    "user_metadata": {
                        "tenant_id": tenant_id,
                        "role": "institution_admin",
                        "full_name": (body.admin_full_name or "").strip(),
                        "must_change_password": True,
                    },
                }
            )
            _set_provisioned_profile(
                service,
                user_id=u.user.id,
                tenant_id=tenant_id,
                role="institution_admin",
                full_name=body.admin_full_name or "",
            )
            admin = {"id": u.user.id, "email": body.admin_email.strip()}
        except Exception as exc:  # noqa: BLE001
            if "u" in locals() and u.user:
                _delete_auth_user_quietly(service, u.user.id)
            service.table("tenants").delete().eq("id", tenant_id).execute()
            raise HTTPException(
                status_code=400,
                detail=f"Could not create institution admin: {exc}",
            )

    return {"id": tenant_id, "name": name, "subdomain": subdomain, "admin": admin}


# ── Super-admin: global question bank (cross-tenant, grouped by course) ───────
@router.get("/platform/question-bank")
def platform_question_bank(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Every question on the platform, grouped by course. Real counts only."""
    from collections import Counter, defaultdict

    _require_super(profile)
    service = get_service_client()

    questions = (
        service.table("questions")
        .select("chapter_id, difficulty, type")
        .execute()
        .data
        or []
    )
    chapters = {
        c["id"]: c
        for c in (service.table("chapters").select("id, subject_id").execute().data or [])
    }
    subjects = {
        s["id"]: s
        for s in (
            service.table("subjects").select("id, course_id").execute().data or []
        )
    }
    courses = {
        c["id"]: c
        for c in (
            service.table("courses").select("id, name, tenant_id").execute().data or []
        )
    }
    tenants = {
        t["id"]: t["name"]
        for t in (service.table("tenants").select("id, name").execute().data or [])
    }

    agg: dict = defaultdict(
        lambda: {
            "questions": 0,
            "subjects": set(),
            "chapters": set(),
            "difficulty": Counter(),
            "types": Counter(),
        }
    )
    uncategorised = 0
    for q in questions:
        ch = chapters.get(q.get("chapter_id"))
        sub = subjects.get(ch["subject_id"]) if ch else None
        cid = sub.get("course_id") if sub else None
        if not cid:
            uncategorised += 1
            continue
        a = agg[cid]
        a["questions"] += 1
        a["subjects"].add(ch["subject_id"])
        a["chapters"].add(ch["id"])
        a["difficulty"][q.get("difficulty")] += 1
        a["types"][q.get("type")] += 1

    out = []
    for cid, a in agg.items():
        co = courses.get(cid)
        out.append(
            {
                "course": co["name"] if co else "Course",
                "tenant": tenants.get(co["tenant_id"]) if co else None,
                "questions": a["questions"],
                "subjects": len(a["subjects"]),
                "chapters": len(a["chapters"]),
                "difficulty": dict(a["difficulty"]),
                "types": dict(a["types"]),
            }
        )
    out.sort(key=lambda x: -x["questions"])
    return {
        "total": len(questions),
        "courses": out,
        "uncategorised": uncategorised,
    }


# ── Super-admin: Question Quality (AI quality intelligence) ──────────────────
_TYPE_LABELS = {
    "mcq_single": "Single-choice",
    "mcq_multi": "Multiple-choice",
    "true_false": "True/False",
    "numerical": "Numerical",
    "fill_blank": "Fill-in-the-blank",
    "matching": "Matching",
    "unknown": "Unknown",
}
_FIELD_LABELS = {
    "question_text": "Question wording",
    "options": "Options",
    "correct_answer": "Correct answer",
    "explanation": "Explanation",
    "difficulty": "Difficulty",
    "marks": "Marks",
}
# Concrete, per-field prompt advice — the "how to improve the AI" playbook.
_FIELD_ADVICE = {
    "correct_answer": "The AI often marks the wrong option as correct. Add an explicit "
    'self-check step to the prompt ("re-verify the correct answer before finalising").',
    "options": "Answer choices need work. Ask the prompt for plausible, distinct "
    "distractors with no overlap or obvious giveaways.",
    "explanation": "Explanations get rewritten a lot. Require a short step-by-step "
    "justification for every answer.",
    "question_text": "Question wording is edited often. Ask for clear, self-contained "
    "stems that don't rely on seeing the source text.",
    "difficulty": "Difficulty labels are off. Give the prompt a concrete rubric for "
    "easy / medium / hard.",
    "marks": "Marks are adjusted often. Standardise marks per question type in the prompt.",
}


def _type_label(t: str | None) -> str:
    return _TYPE_LABELS.get(t or "", t or "Unknown")


def _field_label(f: str) -> str:
    return _FIELD_LABELS.get(f, f)


def _build_findings(
    *,
    total_generated: int,
    status: dict,
    approval_rate: int,
    types_out: list[dict],
    signals: dict,
    trend: dict,
    failures_14d: int,
) -> list[dict]:
    """Turn the raw quality numbers into ranked, plain-language decisions.

    Deterministic rules only — NO AI. This is the 'data-analyst' layer: it tells
    a super admin what is wrong and exactly what to do about it. Severity drives
    ordering/colour on the dashboard: critical > warn > good > info.
    """
    out: list[dict] = []
    approved_n = signals["approved"]
    keep_rate = signals["kept_as_is_rate"]
    decided_qt = (
        status.get("approved", 0)
        + status.get("rejected", 0)
        + status.get("needs_edit", 0)
    )

    if total_generated == 0:
        out.append(
            {
                "severity": "info",
                "title": "No AI questions generated yet",
                "detail": "Once teachers generate quizzes from uploaded material, this "
                "dashboard fills with real quality data.",
                "action": "Generate a quiz to get started.",
            }
        )
        return out

    # 1) Headline verdict — prefer behavioural keep-rate, fall back to approval.
    if approved_n > 0:
        if keep_rate >= 80:
            out.append(
                {
                    "severity": "good",
                    "title": f"AI quality is strong — {keep_rate}% kept as-is",
                    "detail": f"Teachers keep {keep_rate}% of approved questions exactly "
                    "as the AI wrote them.",
                    "action": "Keep the current prompts; focus on the weak spots below.",
                }
            )
        elif keep_rate >= 60:
            out.append(
                {
                    "severity": "warn",
                    "title": f"AI quality is decent — {keep_rate}% kept as-is",
                    "detail": f"Teachers still edit about {100 - keep_rate}% of approved "
                    "questions before using them.",
                    "action": "Target the most-edited field below to push past 80%.",
                }
            )
        else:
            out.append(
                {
                    "severity": "critical",
                    "title": f"AI quality needs work — only {keep_rate}% kept as-is",
                    "detail": f"Teachers rewrite most approved questions "
                    f"({100 - keep_rate}%). The prompts need attention.",
                    "action": "Start with the most-edited field and weakest type below.",
                }
            )
    elif decided_qt == 0:
        out.append(
            {
                "severity": "info",
                "title": "No questions reviewed yet",
                "detail": f"{total_generated} AI questions are waiting. Quality signal "
                "appears once teachers approve, edit or reject them.",
                "action": "Ask teachers to review the pending questions.",
            }
        )
    else:
        out.append(
            {
                "severity": "good" if approval_rate >= 70 else "warn",
                "title": f"{approval_rate}% approval rate so far",
                "detail": f"Of {decided_qt} reviewed questions, {approval_rate}% were "
                "approved. 'Kept as-is' quality sharpens as more reviews come in.",
                "action": "Encourage teachers to Edit (not reject+regenerate) so we "
                "learn exactly what to fix.",
            }
        )

    # 2) Weakest question type (needs a little volume to matter).
    weak = [t for t in types_out if t["total"] >= 3]
    if weak:
        worst = min(weak, key=lambda t: t["approval"])
        if worst["approval"] < 70:
            out.append(
                {
                    "severity": "critical" if worst["approval"] < 50 else "warn",
                    "title": f"{_type_label(worst['type'])} is the weakest type "
                    f"({worst['approval']}% approved)",
                    "detail": f"Only {worst['approved']} of {worst['total']} "
                    f"{_type_label(worst['type'])} questions were approved — the biggest "
                    "quality drag by type.",
                    "action": f"Review the generation prompt specifically for "
                    f"{_type_label(worst['type'])} questions.",
                }
            )

    # 3) Most-edited field -> concrete prompt fix.
    fields = signals["most_edited_fields"]
    if fields:
        top = fields[0]
        out.append(
            {
                "severity": "warn",
                "title": f"Teachers most often fix: {_field_label(top['field'])}",
                "detail": f"{_field_label(top['field'])} was edited {top['count']} "
                "time(s) — the clearest thing to improve in the prompt.",
                "action": _FIELD_ADVICE.get(
                    top["field"], "Tighten this part of the generation prompt."
                ),
            }
        )

    # 4) Week-over-week trend.
    if trend["has_trend"] and (trend["approved_last7"] + trend["approved_prev7"]) >= 4:
        d = trend["keep_rate_delta"]
        if d >= 5:
            out.append(
                {
                    "severity": "good",
                    "title": f"Quality is improving (+{d} pts this week)",
                    "detail": f"Kept-as-is rate rose from {trend['keep_rate_prev7']}% to "
                    f"{trend['keep_rate_last7']}% week-over-week.",
                    "action": "Whatever changed recently is working — keep going.",
                }
            )
        elif d <= -5:
            out.append(
                {
                    "severity": "critical",
                    "title": f"Quality is slipping ({d} pts this week)",
                    "detail": f"Kept-as-is rate fell from {trend['keep_rate_prev7']}% to "
                    f"{trend['keep_rate_last7']}% week-over-week.",
                    "action": "Check any recent prompt or model changes.",
                }
            )

    # 5) Generation failures.
    if failures_14d > 0:
        out.append(
            {
                "severity": "critical",
                "title": f"{failures_14d} generation failure(s) in 14 days",
                "detail": "The AI failed to return usable questions on some runs — "
                "teachers may have hit errors.",
                "action": "Check the LLM API logs and the prompt's robustness / fallback.",
            }
        )

    # 6) Review backlog.
    pending = status.get("pending_review", 0)
    if pending >= 10:
        out.append(
            {
                "severity": "info",
                "title": f"{pending} questions await review",
                "detail": "A review backlog slows quiz publishing and blurs these numbers.",
                "action": "Clear the review queue to sharpen the quality signal.",
            }
        )

    # 7) Low-volume caveat.
    if total_generated < 20:
        out.append(
            {
                "severity": "info",
                "title": "Early days — numbers will firm up",
                "detail": f"Only {total_generated} AI questions so far. Treat percentages "
                "as directional until volume grows.",
                "action": "Revisit after more quizzes are generated and reviewed.",
            }
        )

    return out


# ── Super-admin: AI generation monitoring ────────────────────────────────────
@router.get("/platform/ai-monitoring")
def platform_ai_monitoring(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """AI generation health across the platform: volume, quality by type, pipeline."""
    from collections import Counter, defaultdict
    from datetime import date, datetime, timedelta

    _require_super(profile)
    service = get_service_client()

    rows = (
        service.table("questions")
        .select("type, difficulty, review_status, source, created_at")
        .execute()
        .data
        or []
    )
    ai = [q for q in rows if q.get("source") == "ai_generated"]
    status = Counter(q.get("review_status") for q in ai)
    decided = (
        status.get("approved", 0)
        + status.get("rejected", 0)
        + status.get("needs_edit", 0)
    )
    approval_rate = round(status.get("approved", 0) / decided * 100) if decided else 0

    by_type: dict = defaultdict(lambda: {"total": 0, "approved": 0})
    for q in ai:
        bt = by_type[q.get("type")]
        bt["total"] += 1
        if q.get("review_status") == "approved":
            bt["approved"] += 1
    types_out = sorted(
        [
            {
                "type": k,
                "total": v["total"],
                "approved": v["approved"],
                "approval": round(v["approved"] / v["total"] * 100) if v["total"] else 0,
            }
            for k, v in by_type.items()
        ],
        key=lambda x: -x["total"],
    )

    today = date.today()
    window = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
    dc = {d.isoformat(): 0 for d in window}
    for q in ai:
        ca = q.get("created_at")
        if ca and ca[:10] in dc:
            dc[ca[:10]] += 1
    volume = [{"date": d.isoformat()[5:], "generated": dc[d.isoformat()]} for d in window]

    # ---- Behavioral quality signals from the events ledger ----------------
    # These are the TRUE "is the AI good enough?" numbers — especially
    # kept-as-is (approved without any edit), which cannot be derived from the
    # questions table. Empty until teachers act after instrumentation started.
    from app.services.events import (
        GENERATION_FAILED,
        QUESTION_APPROVED,
        QUESTION_EDITED,
        QUESTION_GENERATED,
        QUESTION_REGENERATED,
        QUESTION_REJECTED,
        QUIZ_PUBLISHED,
    )

    evs = (
        service.table("events")
        .select("event_type, subject_id, metadata, created_at")
        .in_(
            "event_type",
            [
                QUESTION_GENERATED,
                QUESTION_EDITED,
                QUESTION_APPROVED,
                QUESTION_REJECTED,
                QUESTION_REGENERATED,
                QUIZ_PUBLISHED,
                GENERATION_FAILED,
            ],
        )
        .execute()
        .data
        or []
    )
    gen_type: dict = {}
    edited_ids: set = set()
    approved_ids: set = set()
    approved_at: dict = {}
    rejected_ids: set = set()
    regenerated = 0
    published_n = 0
    failed_dates: list = []
    edited_fields: Counter = Counter()
    first_ev = None
    for e in evs:
        et, sid = e["event_type"], e.get("subject_id")
        md = e.get("metadata") or {}
        ca = e.get("created_at")
        if ca and (first_ev is None or ca < first_ev):
            first_ev = ca
        if et == QUESTION_GENERATED and sid:
            gen_type[sid] = md.get("type")
        elif et == QUESTION_EDITED:
            if sid:
                edited_ids.add(sid)
            for f in md.get("edited_fields") or []:
                edited_fields[f] += 1
        elif et == QUESTION_APPROVED and sid:
            approved_ids.add(sid)
            if ca:
                approved_at[sid] = ca
        elif et == QUESTION_REJECTED and sid:
            rejected_ids.add(sid)
        elif et == QUESTION_REGENERATED:
            regenerated += 1
        elif et == QUIZ_PUBLISHED:
            published_n += 1
        elif et == GENERATION_FAILED and ca:
            failed_dates.append(ca)

    approved_n, rejected_n = len(approved_ids), len(rejected_ids)
    reviewed_n = approved_n + rejected_n
    kept_as_is = len(approved_ids - edited_ids)
    decided_ids = approved_ids | rejected_ids
    pending_n = sum(1 for s in gen_type if s not in decided_ids)

    sig_type: dict = defaultdict(lambda: {"generated": 0, "approved": 0, "kept": 0})
    for sid, ty in gen_type.items():
        bucket = sig_type[ty or "unknown"]
        bucket["generated"] += 1
        if sid in approved_ids:
            bucket["approved"] += 1
            if sid not in edited_ids:
                bucket["kept"] += 1
    sig_by_type = sorted(
        [
            {
                "type": k,
                "generated": v["generated"],
                "approved": v["approved"],
                "kept_as_is": v["kept"],
                "kept_rate": round(v["kept"] / v["approved"] * 100) if v["approved"] else 0,
            }
            for k, v in sig_type.items()
        ],
        key=lambda x: -x["generated"],
    )

    signals = {
        "measured_from": first_ev[:10] if first_ev else None,
        "generated": len(gen_type),
        "reviewed": reviewed_n,
        "approved": approved_n,
        "rejected": rejected_n,
        "kept_as_is": kept_as_is,
        "approved_after_edit": approved_n - kept_as_is,
        "regenerated": regenerated,
        "pending": pending_n,
        "approval_rate": round(approved_n / reviewed_n * 100) if reviewed_n else 0,
        "kept_as_is_rate": round(kept_as_is / approved_n * 100) if approved_n else 0,
        "by_type": sig_by_type,
        "most_edited_fields": [
            {"field": f, "count": c} for f, c in edited_fields.most_common(6)
        ],
    }

    # ---- Trend: last 7 days vs the 7 days before (from approval events) -----
    iso7 = (today - timedelta(days=7)).isoformat()
    iso14 = (today - timedelta(days=14)).isoformat()
    last7 = {"approved": 0, "kept": 0}
    prev7 = {"approved": 0, "kept": 0}
    for sid, ca in approved_at.items():
        day = ca[:10]
        kept = 1 if sid not in edited_ids else 0
        if day >= iso7:
            last7["approved"] += 1
            last7["kept"] += kept
        elif day >= iso14:
            prev7["approved"] += 1
            prev7["kept"] += kept
    keep_last = round(last7["kept"] / last7["approved"] * 100) if last7["approved"] else 0
    keep_prev = round(prev7["kept"] / prev7["approved"] * 100) if prev7["approved"] else 0
    trend = {
        "keep_rate_last7": keep_last,
        "keep_rate_prev7": keep_prev,
        "keep_rate_delta": keep_last - keep_prev,
        "approved_last7": last7["approved"],
        "approved_prev7": prev7["approved"],
        "has_trend": (last7["approved"] + prev7["approved"]) > 0,
    }

    # ---- AI generation failures (last 14 days) ------------------------------
    failures_14d = sum(1 for d in failed_dates if d[:10] >= iso14)

    # ---- Quality by difficulty (from the questions table) -------------------
    diff_q: dict = defaultdict(lambda: {"total": 0, "approved": 0})
    for q in ai:
        b = diff_q[q.get("difficulty") or "unspecified"]
        b["total"] += 1
        if q.get("review_status") == "approved":
            b["approved"] += 1
    difficulty_quality = sorted(
        [
            {
                "difficulty": k,
                "total": v["total"],
                "approved": v["approved"],
                "approval": round(v["approved"] / v["total"] * 100) if v["total"] else 0,
            }
            for k, v in diff_q.items()
        ],
        key=lambda x: -x["total"],
    )

    # ---- Quality funnel (question lifecycle, questions table + events) ------
    reviewed_qt = (
        status.get("approved", 0)
        + status.get("rejected", 0)
        + status.get("needs_edit", 0)
    )
    funnel = [
        {"stage": "Generated", "count": len(ai)},
        {"stage": "Reviewed", "count": reviewed_qt},
        {"stage": "Approved", "count": status.get("approved", 0)},
        {"stage": "Kept as-is", "count": kept_as_is},
    ]

    # ---- Findings & recommendations (the decision layer — no AI) ------------
    findings = _build_findings(
        total_generated=len(ai),
        status=status,
        approval_rate=approval_rate,
        types_out=types_out,
        signals=signals,
        trend=trend,
        failures_14d=failures_14d,
    )

    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total_generated": len(ai),
        "approval_rate": approval_rate,
        "published_quizzes": published_n,
        "failures_14d": failures_14d,
        "pipeline": {
            "pending_review": status.get("pending_review", 0),
            "approved": status.get("approved", 0),
            "rejected": status.get("rejected", 0),
            "needs_edit": status.get("needs_edit", 0),
        },
        "by_type": types_out,
        "by_difficulty": dict(Counter(q.get("difficulty") for q in ai)),
        "difficulty_quality": difficulty_quality,
        "volume": volume,
        "trend": trend,
        "funnel": funnel,
        "findings": findings,
        "signals": signals,
    }


# ── Institution admin: quiz performance ─────────────────────────────────────
class ReviewStatusCounts(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    needs_edit: int = 0


class AdminQuizSet(BaseModel):
    id: str
    title: str
    status: str
    subject: str | None
    subject_id: str | None
    course: str | None
    course_id: str | None
    teacher: str | None
    teacher_id: str | None
    questions: int
    attempts_count: int
    avg_accuracy: float
    created_at: datetime | None
    published_at: datetime | None
    last_attempted_at: datetime | None
    review_status: ReviewStatusCounts


@router.get("/admin/quiz-sets", response_model=list[AdminQuizSet])
def admin_quiz_sets(
    profile: CurrentProfile = Depends(get_current_profile),
    teacher_id: str | None = None,
) -> list[AdminQuizSet]:
    """
    Every quiz set in the institution, enriched with course/subject/teacher and a
    question/review counts and graded-attempt performance.
    """
    _require_admin(profile)
    service = get_service_client()
    t = profile.tenant_id

    sets_query = (
        service.table("quiz_sets")
        .select(
            "id, title, status, subject_id, created_by, created_at, published_at"
        )
        .eq("tenant_id", t)
    )
    if teacher_id:
        sets_query = sets_query.eq("created_by", teacher_id)
    sets = sets_query.order("created_at", desc=True).execute().data or []
    if not sets:
        return []

    subject_ids = list({s["subject_id"] for s in sets if s.get("subject_id")})
    subjects = (
        {
            s["id"]: s
            for s in (
                service.table("subjects")
                .select("id, name, course_id")
                .eq("tenant_id", t)
                .in_("id", subject_ids)
                .execute()
                .data
                or []
            )
        }
        if subject_ids
        else {}
    )
    course_ids = list({s["course_id"] for s in subjects.values() if s.get("course_id")})
    courses = (
        {
            c["id"]: c["name"]
            for c in (
                service.table("courses")
                .select("id, name")
                .eq("tenant_id", t)
                .in_("id", course_ids)
                .execute()
                .data
                or []
            )
        }
        if course_ids
        else {}
    )
    teacher_ids = list({s["created_by"] for s in sets if s.get("created_by")})
    teachers = (
        {
            p["id"]: p.get("full_name")
            for p in (
                service.table("profiles")
                .select("id, full_name")
                .eq("tenant_id", t)
                .eq("role", "teacher")
                .in_("id", teacher_ids)
                .execute()
                .data
                or []
            )
        }
        if teacher_ids
        else {}
    )

    set_ids = [s["id"] for s in sets]
    variants = (
        service.table("quiz_variants")
        .select("id, quiz_set_id, total_marks")
        .eq("tenant_id", t)
        .in_("quiz_set_id", set_ids)
        .execute()
        .data
        or []
    )
    var_to_set = {v["id"]: v["quiz_set_id"] for v in variants}
    var_marks = {v["id"]: float(v.get("total_marks") or 0) for v in variants}
    vq = (
        service.table("quiz_variant_questions")
        .select("variant_id, question_id")
        .eq("tenant_id", t)
        .in_("variant_id", list(var_to_set))
        .execute()
        .data
        if var_to_set
        else []
    )
    question_ids_by_set: dict[str, set[str]] = {}
    for row in vq:
        quiz_set_id = var_to_set.get(row["variant_id"])
        if quiz_set_id:
            question_ids_by_set.setdefault(quiz_set_id, set()).add(row["question_id"])
    question_ids = list({question_id for ids in question_ids_by_set.values() for question_id in ids})
    questions = (
        service.table("questions")
        .select("id, review_status")
        .eq("tenant_id", t)
        .in_("id", question_ids)
        .execute()
        .data
        if question_ids
        else []
    )
    review_by_question = {
        question["id"]: question.get("review_status") for question in questions
    }

    attempts = (
        service.table("quiz_attempts")
        .select("id, variant_id, total_score, submitted_at")
        .eq("tenant_id", t)
        .eq("status", "graded")
        .in_("variant_id", list(var_to_set))
        .execute()
        .data
        if var_to_set
        else []
    )
    attempt_stats: dict[str, dict] = {}
    for attempt in attempts:
        quiz_set_id = var_to_set.get(attempt["variant_id"])
        maximum = var_marks.get(attempt["variant_id"], 0)
        if not quiz_set_id:
            continue
        bucket = attempt_stats.setdefault(
            quiz_set_id,
            {"count": 0, "score": 0.0, "maximum": 0.0, "last": None},
        )
        bucket["count"] += 1
        submitted_at = attempt.get("submitted_at")
        if submitted_at and (bucket["last"] is None or submitted_at > bucket["last"]):
            bucket["last"] = submitted_at
        if maximum > 0:
            bucket["score"] += float(attempt.get("total_score") or 0)
            bucket["maximum"] += maximum

    out: list[AdminQuizSet] = []
    for s in sets:
        sub = subjects.get(s.get("subject_id"))
        quiz_question_ids = question_ids_by_set.get(s["id"], set())
        reviews = Counter(review_by_question.get(question_id) for question_id in quiz_question_ids)
        stats = attempt_stats.get(s["id"], {})
        score = float(stats.get("score", 0))
        maximum = float(stats.get("maximum", 0))
        out.append(
            AdminQuizSet(
                id=str(s["id"]),
                title=s["title"],
                status=s["status"],
                subject=sub["name"] if sub else None,
                subject_id=str(s["subject_id"]) if s.get("subject_id") else None,
                course=courses.get(sub["course_id"]) if sub else None,
                course_id=str(sub["course_id"]) if sub and sub.get("course_id") else None,
                teacher=teachers.get(s.get("created_by")),
                teacher_id=str(s["created_by"]) if s.get("created_by") else None,
                questions=len(quiz_question_ids),
                attempts_count=int(stats.get("count", 0)),
                avg_accuracy=round(max(0, min(100, score / maximum * 100)), 1)
                if maximum
                else 0,
                created_at=s.get("created_at"),
                published_at=s.get("published_at"),
                last_attempted_at=stats.get("last"),
                review_status=ReviewStatusCounts(
                    pending=reviews.get("pending_review", 0),
                    approved=reviews.get("approved", 0),
                    rejected=reviews.get("rejected", 0),
                    needs_edit=reviews.get("needs_edit", 0),
                ),
            )
        )
    return out


class TeacherAnalyticsDetail(BaseModel):
    teacher_id: str
    teacher_name: str
    quiz_sets_created: int
    quiz_sets_published: int
    total_attempts: int
    avg_accuracy: float
    last_quiz_created: datetime | None
    is_active: bool
    course_names: list[str]


class TeacherAnalyticsSummary(BaseModel):
    total_teachers: int
    active_teachers: int
    avg_accuracy: float
    total_quiz_sets: int
    total_published: int
    total_attempts: int


class TeacherAnalyticsResponse(BaseModel):
    teachers: list[TeacherAnalyticsDetail]
    summary: TeacherAnalyticsSummary


@router.get("/admin/teachers/analytics", response_model=TeacherAnalyticsResponse)
def admin_teacher_analytics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> TeacherAnalyticsResponse:
    """Tenant-wide faculty activity, engagement, and student outcomes."""
    _require_admin(profile)
    service = get_service_client()
    tenant_id = profile.tenant_id

    teachers = (
        service.table("profiles")
        .select("id, full_name")
        .eq("tenant_id", tenant_id)
        .eq("role", "teacher")
        .execute()
        .data
        or []
    )
    quiz_sets = (
        service.table("quiz_sets")
        .select("id, created_by, subject_id, status, created_at")
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    subject_ids = list(
        {row["subject_id"] for row in quiz_sets if row.get("subject_id")}
    )
    subjects = (
        service.table("subjects")
        .select("id, course_id")
        .eq("tenant_id", tenant_id)
        .in_("id", subject_ids)
        .execute()
        .data
        if subject_ids
        else []
    )
    subject_course = {row["id"]: row.get("course_id") for row in subjects}
    course_ids = list(
        {course_id for course_id in subject_course.values() if course_id}
    )
    courses = (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", tenant_id)
        .in_("id", course_ids)
        .execute()
        .data
        if course_ids
        else []
    )
    course_names = {row["id"]: row["name"] for row in courses}

    quiz_set_ids = [row["id"] for row in quiz_sets]
    variants = (
        service.table("quiz_variants")
        .select("id, quiz_set_id, total_marks")
        .eq("tenant_id", tenant_id)
        .in_("quiz_set_id", quiz_set_ids)
        .execute()
        .data
        if quiz_set_ids
        else []
    )
    variant_quiz_set = {row["id"]: row["quiz_set_id"] for row in variants}
    variant_marks = {
        row["id"]: float(row.get("total_marks") or 0) for row in variants
    }
    variant_ids = list(variant_quiz_set)
    attempts = (
        service.table("quiz_attempts")
        .select("variant_id, status, total_score")
        .eq("tenant_id", tenant_id)
        .in_("variant_id", variant_ids)
        .execute()
        .data
        if variant_ids
        else []
    )

    quiz_set_teacher = {
        row["id"]: row.get("created_by") for row in quiz_sets
    }
    sets_by_teacher: dict[str, list[dict]] = {}
    for row in quiz_sets:
        teacher_id = row.get("created_by")
        if teacher_id:
            sets_by_teacher.setdefault(teacher_id, []).append(row)

    attempts_by_teacher: Counter = Counter()
    score_by_teacher: Counter = Counter()
    maximum_by_teacher: Counter = Counter()
    for attempt in attempts:
        variant_id = attempt.get("variant_id")
        quiz_set_id = variant_quiz_set.get(variant_id)
        teacher_id = quiz_set_teacher.get(quiz_set_id)
        if not teacher_id:
            continue
        attempts_by_teacher[teacher_id] += 1
        maximum = variant_marks.get(variant_id, 0)
        if attempt.get("status") == "graded" and maximum > 0:
            score_by_teacher[teacher_id] += float(attempt.get("total_score") or 0)
            maximum_by_teacher[teacher_id] += maximum

    active_since = datetime.now(timezone.utc) - timedelta(days=30)
    details: list[TeacherAnalyticsDetail] = []
    for teacher in teachers:
        teacher_id = teacher["id"]
        teacher_sets = sets_by_teacher.get(teacher_id, [])
        created_values = [row.get("created_at") for row in teacher_sets if row.get("created_at")]
        last_created_value = max(created_values) if created_values else None
        last_created = (
            datetime.fromisoformat(last_created_value.replace("Z", "+00:00"))
            if last_created_value
            else None
        )
        if last_created and last_created.tzinfo is None:
            last_created = last_created.replace(tzinfo=timezone.utc)
        maximum = float(maximum_by_teacher.get(teacher_id, 0))
        teacher_course_names = sorted(
            {
                course_names[course_id]
                for row in teacher_sets
                if (course_id := subject_course.get(row.get("subject_id")))
                and course_id in course_names
            }
        )
        details.append(
            TeacherAnalyticsDetail(
                teacher_id=str(teacher_id),
                teacher_name=teacher.get("full_name") or "Unnamed teacher",
                quiz_sets_created=len(teacher_sets),
                quiz_sets_published=sum(
                    1 for row in teacher_sets if row.get("status") == "published"
                ),
                total_attempts=int(attempts_by_teacher.get(teacher_id, 0)),
                avg_accuracy=(
                    round(
                        max(
                            0,
                            min(
                                100,
                                float(score_by_teacher.get(teacher_id, 0))
                                / maximum
                                * 100,
                            ),
                        ),
                        1,
                    )
                    if maximum
                    else 0
                ),
                last_quiz_created=last_created,
                is_active=bool(last_created and last_created >= active_since),
                course_names=teacher_course_names,
            )
        )

    details.sort(
        key=lambda row: (
            -row.total_attempts,
            -row.quiz_sets_created,
            row.teacher_name.lower(),
        )
    )
    total_score = float(sum(score_by_teacher.values()))
    total_maximum = float(sum(maximum_by_teacher.values()))
    return TeacherAnalyticsResponse(
        teachers=details,
        summary=TeacherAnalyticsSummary(
            total_teachers=len(details),
            active_teachers=sum(1 for row in details if row.is_active),
            avg_accuracy=(
                round(max(0, min(100, total_score / total_maximum * 100)), 1)
                if total_maximum
                else 0
            ),
            total_quiz_sets=len(quiz_sets),
            total_published=sum(
                1 for row in quiz_sets if row.get("status") == "published"
            ),
            total_attempts=len(attempts),
        ),
    )


@router.get("/admin/quiz-sets/{quiz_set_id}")
def admin_quiz_set_detail(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Detailed question and student performance for one tenant quiz set."""
    _require_admin(profile)
    service = get_service_client()
    tenant_id = profile.tenant_id
    summary = next(
        (row for row in admin_quiz_sets(profile) if row.id == quiz_set_id),
        None,
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Quiz set not found.")

    variants = (
        service.table("quiz_variants")
        .select("id, total_marks")
        .eq("tenant_id", tenant_id)
        .eq("quiz_set_id", quiz_set_id)
        .execute()
        .data
        or []
    )
    variant_ids = [row["id"] for row in variants]
    variant_marks = {
        row["id"]: float(row.get("total_marks") or 0) for row in variants
    }
    links = (
        service.table("quiz_variant_questions")
        .select("variant_id, question_id")
        .eq("tenant_id", tenant_id)
        .in_("variant_id", variant_ids)
        .execute()
        .data
        if variant_ids
        else []
    )
    question_ids = list({row["question_id"] for row in links})
    questions = (
        service.table("questions")
        .select("id, question_text, type, difficulty, review_status")
        .eq("tenant_id", tenant_id)
        .in_("id", question_ids)
        .execute()
        .data
        if question_ids
        else []
    )
    attempts = (
        service.table("quiz_attempts")
        .select("id, student_id, variant_id, total_score, submitted_at")
        .eq("tenant_id", tenant_id)
        .eq("status", "graded")
        .in_("variant_id", variant_ids)
        .execute()
        .data
        if variant_ids
        else []
    )
    student_ids = list({row["student_id"] for row in attempts if row.get("student_id")})
    students = (
        service.table("profiles")
        .select("id, full_name")
        .eq("tenant_id", tenant_id)
        .eq("role", "student")
        .in_("id", student_ids)
        .execute()
        .data
        if student_ids
        else []
    )
    student_names = {
        row["id"]: row.get("full_name") or "Unnamed student" for row in students
    }
    attempt_ids = [row["id"] for row in attempts]
    answers = (
        service.table("attempt_answers")
        .select("attempt_id, question_id, is_correct")
        .eq("tenant_id", tenant_id)
        .in_("attempt_id", attempt_ids)
        .in_("question_id", question_ids)
        .execute()
        .data
        if attempt_ids and question_ids
        else []
    )

    by_type = Counter(question.get("type") or "unspecified" for question in questions)
    by_difficulty = Counter(
        question.get("difficulty") or "unspecified" for question in questions
    )
    student_performance = []
    for attempt in attempts:
        maximum = variant_marks.get(attempt["variant_id"], 0)
        score = float(attempt.get("total_score") or 0)
        student_performance.append(
            {
                "attempt_id": str(attempt["id"]),
                "student_id": str(attempt["student_id"]),
                "student_name": student_names.get(
                    attempt["student_id"], "Former student"
                ),
                "score": score,
                "max_score": maximum,
                "accuracy": round(max(0, min(100, score / maximum * 100)), 1)
                if maximum
                else 0,
                "submitted_at": attempt.get("submitted_at"),
            }
        )
    student_performance.sort(
        key=lambda row: row.get("submitted_at") or "", reverse=True
    )

    answer_counts: dict[str, dict[str, int]] = {}
    for answer in answers:
        bucket = answer_counts.setdefault(
            answer["question_id"], {"answered": 0, "correct": 0}
        )
        bucket["answered"] += 1
        if answer.get("is_correct") is True:
            bucket["correct"] += 1
    question_by_id = {row["id"]: row for row in questions}
    weak_questions = []
    for question_id, counts in answer_counts.items():
        question = question_by_id.get(question_id)
        if question is None:
            continue
        weak_questions.append(
            {
                "question_id": str(question_id),
                "question_text": question.get("question_text") or "Question",
                "answered": counts["answered"],
                "accuracy": round(counts["correct"] / counts["answered"] * 100, 1),
            }
        )
    weak_questions.sort(key=lambda row: (row["accuracy"], -row["answered"]))

    return {
        "quiz": summary.model_dump(mode="json"),
        "question_breakdown": {
            "by_type": dict(sorted(by_type.items())),
            "by_difficulty": dict(sorted(by_difficulty.items())),
        },
        "student_performance": student_performance,
        "weak_questions": weak_questions[:5],
    }
