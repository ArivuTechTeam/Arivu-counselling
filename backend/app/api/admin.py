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

import asyncio
import base64
import binascii
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_institution_admin, require_super_admin
from app.lib.api_errors import auth_provisioning_error, public_error
from app.lib.supabase import get_service_client
from app.lib.storage import delete_bytes, signed_url, upload_bytes
from app.services.account_deletion import erase_account_data
from app.services.catalog import active_catalog_subject_ids, provision_catalog_subject
from app.services.institution_offerings import (
    institution_offerings_by_tenant,
    offering_counts,
)
from app.services.teacher_access import replace_teacher_subjects
from app.services.tenant_features import normalize_feature_flags

router = APIRouter(prefix="/api/v1", tags=["admin"])

AUTH_USERS_PAGE_SIZE = 1000
POSTGREST_PAGE_SIZE = 1000
ADMIN_DIRECTORY_PAGE_SIZE = 100
ADMIN_QUIZ_SET_PAGE_SIZE_MAX = 100
INSTITUTION_LOGO_MAX_BYTES = 1024 * 1024
INSTITUTION_LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
INSTITUTION_SUBDOMAIN_MAX_LENGTH = 63


def _normalize_institution_subdomain(value: str) -> str:
    subdomain = value.strip().lower()
    if not subdomain:
        raise HTTPException(
            status_code=400,
            detail="Institution access URL is required.",
        )
    if (
        len(subdomain) > INSTITUTION_SUBDOMAIN_MAX_LENGTH
        or not all(
            character in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for character in subdomain
        )
        or not subdomain[0].isalnum()
        or not subdomain[-1].isalnum()
        or "--" in subdomain
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Access URL must use lowercase letters, numbers, "
                "and single internal hyphens only."
            ),
        )
    return subdomain


def _signed_logo_url(path: object) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    try:
        return signed_url(path, expires_in=3600)
    except Exception:  # noqa: BLE001
        # Branding metadata must remain manageable even if Storage is
        # temporarily unavailable; the private object path is never exposed.
        return None


class StrictApiResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectoryUser(StrictApiResponse):
    id: str
    full_name: str | None
    email: str | None
    courses: list[str]
    subject_count: int = 0


class DirectoryPage(StrictApiResponse):
    items: list[DirectoryUser]
    page: int
    page_size: int
    total: int


class IdentifierResult(StrictApiResponse):
    id: str


class ChangedResult(StrictApiResponse):
    changed: bool


class CourseImpact(StrictApiResponse):
    subjects: int
    students: int
    teacher_assignments: int
    quiz_sets: int
    documents: int


class NamedIdentifier(StrictApiResponse):
    id: str
    name: str


class TeacherCourseOut(NamedIdentifier):
    subjects: list[NamedIdentifier]
    student_count: int


class CourseStudentOut(StrictApiResponse):
    id: str
    full_name: str | None
    email: str | None


class CourseRosterOut(StrictApiResponse):
    course: NamedIdentifier
    count: int
    students: list[CourseStudentOut]


class InstitutionStats(StrictApiResponse):
    teachers: int
    students: int
    courses: int
    subjects: int
    quiz_sets: int
    published_quizzes: int


class TenantOption(StrictApiResponse):
    id: str
    name: str
    subdomain: str


class CreatedResult(StrictApiResponse):
    created: bool


class InstitutionCreatedResult(CreatedResult):
    tenant_id: str


class DeletedResult(StrictApiResponse):
    deleted: bool


class InstitutionAdminOut(StrictApiResponse):
    id: str
    full_name: str | None
    email: str | None
    institution: str
    subdomain: str
    courses: list[str]
    course_count: int


class ReviewPipelineFull(StrictApiResponse):
    pending_review: int = 0
    approved: int = 0
    rejected: int = 0
    needs_edit: int = 0


class InstitutionRow(StrictApiResponse):
    id: str
    name: str
    subdomain: str | None
    created_at: datetime | None
    plan_tier: str | None
    is_active: bool
    teachers: int
    students: int
    admins: int
    quiz_sets: int
    published: int
    attempts: int
    accuracy: int
    courses: list[str]
    course_count: int
    level_count: int
    subject_count: int
    logo_url: str | None = None
    logo_filename: str | None = None
    primary_color: str = "#2E8857"
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class PlatformActivityPoint(StrictApiResponse):
    date: str
    attempts: int


class PlatformOverviewResponse(StrictApiResponse):
    institutions: int
    active_institutions: int
    teachers: int
    students: int
    admins: int
    quiz_sets: int
    published_quizzes: int
    questions: int
    documents: int
    attempts: int
    accuracy: int
    approval_rate: int
    pipeline: ReviewPipelineFull
    activity: list[PlatformActivityPoint]
    institutions_table: list[InstitutionRow]


class PlatformTenantStats(StrictApiResponse):
    id: str
    name: str
    teachers: int
    students: int


class PlatformStatsResponse(StrictApiResponse):
    institutions: int
    total_teachers: int
    total_students: int
    per_institution: list[PlatformTenantStats]


class TenantDetails(StrictApiResponse):
    id: str
    name: str
    subdomain: str
    plan_tier: str
    is_active: bool
    created_at: datetime | None = None
    logo_url: str | None = None
    logo_filename: str | None = None
    primary_color: str = "#2E8857"
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class OfferingSubject(StrictApiResponse):
    id: str
    name: str


class OfferingLevel(StrictApiResponse):
    id: str
    name: str
    subjects: list[OfferingSubject]


class OfferingCourse(StrictApiResponse):
    id: str
    name: str
    levels: list[OfferingLevel]


class TenantOfferings(StrictApiResponse):
    tenant_id: str
    courses: list[OfferingCourse]


class QuestionBankCourse(StrictApiResponse):
    course: str
    tenant: str | None
    questions: int
    subjects: int
    chapters: int
    difficulty: dict[str, int]
    types: dict[str, int]
    review_status: ReviewPipelineFull


class QuestionBankResponse(StrictApiResponse):
    total: int
    courses: list[QuestionBankCourse]
    uncategorised: int


class AiTypeQuality(StrictApiResponse):
    type: str
    total: int
    approved: int
    approval: int


class AiDifficultyQuality(StrictApiResponse):
    difficulty: str
    total: int
    approved: int
    approval: int


class AiSignalType(StrictApiResponse):
    type: str
    generated: int
    approved: int
    kept_as_is: int
    kept_rate: int


class AiQualitySignals(StrictApiResponse):
    measured_from: str | None
    generated: int
    reviewed: int
    approved: int
    rejected: int
    kept_as_is: int
    approved_after_edit: int
    regenerated: int
    pending: int
    approval_rate: int
    kept_as_is_rate: int
    by_type: list[AiSignalType]
    most_edited_fields: list[dict[str, int | str]]


class QualityTrend(StrictApiResponse):
    keep_rate_last7: int
    keep_rate_prev7: int
    keep_rate_delta: int
    approved_last7: int
    approved_prev7: int
    has_trend: bool


class PlatformQualityFinding(StrictApiResponse):
    severity: Literal["critical", "warn", "good", "info"]
    title: str
    detail: str
    action: str


class AiMonitoringResponse(StrictApiResponse):
    updated_at: datetime
    total_generated: int
    approval_rate: int
    published_quizzes: int
    failures_14d: int
    pipeline: ReviewPipelineFull
    by_type: list[AiTypeQuality]
    by_difficulty: dict[str, int]
    difficulty_quality: list[AiDifficultyQuality]
    volume: list[dict[str, int | str]]
    trend: QualityTrend
    funnel: list[dict[str, int | str]]
    findings: list[PlatformQualityFinding]
    signals: AiQualitySignals


def _rpc_json(service, function_name: str) -> dict:
    """Return one JSON object from a service-role-only Postgres RPC."""
    data = service.rpc(function_name, {}).execute().data
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and len(data) == 1:
        row = data[0]
        if isinstance(row, dict) and len(row) == 1:
            value = next(iter(row.values()))
            if isinstance(value, dict):
                return value
        if isinstance(row, dict):
            return row
    raise RuntimeError(f"{function_name} returned an invalid analytics payload")


def _count(service, table: str, tenant_id: str, **filters) -> int:
    q = service.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in filters.items():
        q = q.eq(k, v)
    return len(q.execute().data or [])


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


def _email_by_auth_user_id(
    service, user_ids: list[str] | set[str]
) -> dict[str, str | None]:
    """Resolve only requested Auth emails without retaining the whole directory."""
    remaining = {str(user_id) for user_id in user_ids}
    emails: dict[str, str | None] = {}
    page = 1
    while remaining:
        response = service.auth.admin.list_users(
            page=page, per_page=AUTH_USERS_PAGE_SIZE
        )
        page_users = list(getattr(response, "users", response) or [])
        for user in page_users:
            user_id = str(user.id)
            if user_id in remaining:
                emails[user_id] = getattr(user, "email", None)
                remaining.remove(user_id)
        if len(page_users) < AUTH_USERS_PAGE_SIZE:
            break
        page += 1
    return emails


def _email_by_auth_user_id_direct(
    service, user_ids: list[str] | set[str]
) -> dict[str, str | None]:
    """Resolve a bounded directory page without scanning the global Auth list."""
    emails: dict[str, str | None] = {}
    for user_id in user_ids:
        try:
            response = service.auth.admin.get_user_by_id(str(user_id))
            user = getattr(response, "user", response)
            emails[str(user_id)] = getattr(user, "email", None)
        except Exception:  # noqa: BLE001 - one missing Auth row must not hide the page
            emails[str(user_id)] = None
    return emails


def _select_all(
    service,
    table: str,
    columns: str,
    *,
    configure: Callable | None = None,
) -> list[dict]:
    """Read a complete PostgREST collection without the 1,000-row truncation."""
    rows: list[dict] = []
    start = 0
    while True:
        query = service.table(table).select(columns)
        if configure is not None:
            query = configure(query)
        page = (
            query.order("id")
            .range(start, start + POSTGREST_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < POSTGREST_PAGE_SIZE:
            return rows
        start += POSTGREST_PAGE_SIZE


def _set_provisioned_profile(
    service, *, user_id: str, tenant_id: str, role: str, full_name: str
) -> None:
    saved = (
        service.table("profiles")
        .upsert(
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "role": role,
                "full_name": full_name.strip(),
                "must_change_password": True,
            },
            on_conflict="id",
        )
        .execute()
    )
    if not saved.data:
        raise RuntimeError("The authorization profile could not be saved.")


def _rollback_provisioned_user(service, user_id: str) -> None:
    """Remove a failed provisioned identity or fail loudly for operator action."""
    service.auth.admin.delete_user(user_id)


def _rollback_tenant(service, tenant_id: str) -> None:
    """Remove a failed tenant, deactivating it if deletion cannot complete."""
    try:
        service.table("tenants").delete().eq("id", tenant_id).execute()
    except Exception:
        # A failed Auth cleanup may leave a profile FK behind. Quarantine the
        # tenant so no public signup or new provisioning can use it.
        service.table("tenants").update({"is_active": False}).eq(
            "id", tenant_id
        ).execute()
        raise


# ── Institution teacher management ──────────────────────────────────────────
@router.get("/users", response_model=DirectoryPage)
def list_users(
    page: int = 1,
    page_size: int = 12,
    q: str = "",
    profile: CurrentProfile = Depends(get_current_profile),
) -> DirectoryPage:
    """Return one tenant-scoped page of institution teachers."""
    require_institution_admin(profile)
    if page < 1 or page_size < 1 or page_size > ADMIN_DIRECTORY_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"page must be positive and page_size must be between 1 and {ADMIN_DIRECTORY_PAGE_SIZE}.",
        )
    service = get_service_client()

    normalized_query = q.strip()
    if len(normalized_query) > 100:
        raise HTTPException(status_code=400, detail="Search text is too long.")

    start = (page - 1) * page_size
    profiles_query = (
        service.table("profiles")
        .select("id, full_name, created_at", count="exact")
        .eq("tenant_id", profile.tenant_id)
        .eq("role", "teacher")
    )
    if normalized_query:
        profiles_query = profiles_query.ilike("full_name", f"%{normalized_query}%")
    response = (
        profiles_query.order("created_at", desc=True)
        .range(start, start + page_size - 1)
        .execute()
    )
    teachers = response.data or []
    total = int(response.count or 0)
    if not teachers:
        return DirectoryPage(items=[], page=page, page_size=page_size, total=total)
    teachers.sort(key=lambda teacher: teacher.get("created_at") or "", reverse=True)
    teacher_ids = {str(teacher["id"]) for teacher in teachers}
    email_by_id = _email_by_auth_user_id_direct(service, teacher_ids)

    assignments = _select_all(
        service,
        "teacher_subjects",
        "id, teacher_id, subject_id",
        configure=lambda query: query.eq("tenant_id", profile.tenant_id).in_(
            "teacher_id", list(teacher_ids)
        ),
    )
    subject_ids = list({str(row["subject_id"]) for row in assignments})
    subjects = []
    if subject_ids:
        subjects = _select_all(
            service,
            "subjects",
            "id, course_id",
            configure=lambda query: query.eq(
                "tenant_id", profile.tenant_id
            ).in_("id", subject_ids),
        )
    courses = _select_all(
        service,
        "courses",
        "id, name",
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
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

    return DirectoryPage(
        items=[DirectoryUser(**{
            "id": teacher["id"],
            "full_name": teacher["full_name"],
            "email": email_by_id.get(teacher["id"]),
            "courses": sorted(
                course_name[course_id]
                for course_id in course_ids_by_teacher.get(str(teacher["id"]), set())
                if course_id in course_name
            ),
            "subject_count": len(
                subjects_by_teacher.get(str(teacher["id"]), set())
            ),
        }) for teacher in teachers],
        page=page,
        page_size=page_size,
        total=total,
    )


class TeacherCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str
    password: str = Field(min_length=12, max_length=128)
    course_id: str
    subject_ids: list[str] = Field(min_length=1, max_length=500)


class TeacherUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str
    subject_ids: list[str] = Field(max_length=500)


class TemporaryPasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=12, max_length=128)


class TemporaryPasswordResetResult(BaseModel):
    changed: bool


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


@router.post("/users", response_model=IdentifierResult)
def create_user(
    body: TeacherCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Create a teacher; students join through the public signup flow."""
    require_institution_admin(profile)
    _validate_temporary_password(body.password)
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
        # Supabase Auth inserts auth.users before it applies app_metadata.
        # The signup trigger uses this non-authorizing routing hint to leave
        # backend-provisioned profiles to the code below.
        "_backend_provisioning_intent": True,
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
            try:
                _rollback_provisioned_user(service, created.user.id)
            except Exception as rollback_exc:  # noqa: BLE001
                raise public_error(
                    500,
                    "The teacher could not be created cleanly and requires operator review.",
                    operation="roll back teacher provisioning",
                    exception=rollback_exc,
                ) from exc
        raise public_error(
            400,
            "We couldn't create this teacher. Check the account details and try again.",
            operation="create teacher",
            exception=exc,
        ) from exc

    # The browser already has the submitted email; only the new identifier is
    # needed to associate the in-memory temporary credential with this row.
    return {"id": created.user.id}


@router.delete("/users/{user_id}", response_model=DeletedResult)
def delete_user(
    user_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile)
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
        erase_account_data(
            service,
            user_id=user_id,
            tenant_id=profile.tenant_id,
        )
        service.auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            503,
            "Could not securely remove this teacher. Please try again.",
            operation="erase teacher account",
            exception=exc,
        ) from exc
    return {"deleted": True}


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


def _validate_temporary_password(password: str) -> None:
    if not any(character.isupper() for character in password):
        raise HTTPException(status_code=400, detail="Password must include uppercase text.")
    if not any(character.islower() for character in password):
        raise HTTPException(status_code=400, detail="Password must include lowercase text.")
    if not any(character.isdigit() for character in password):
        raise HTTPException(status_code=400, detail="Password must include a number.")


@router.post(
    "/users/{user_id}/temporary-password",
    response_model=TemporaryPasswordResetResult,
)
def reset_teacher_temporary_password(
    user_id: str,
    body: TemporaryPasswordReset,
    profile: CurrentProfile = Depends(get_current_profile),
) -> TemporaryPasswordResetResult:
    """Set a browser-generated temporary password without returning it."""
    require_institution_admin(profile)
    _validate_temporary_password(body.password)
    service = get_service_client()
    _assert_tenant_teacher(
        service, teacher_id=user_id, tenant_id=profile.tenant_id
    )
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
        # Keep Auth metadata in sync with the authoritative profile flag.
        # The dashboard reads this value from Supabase Auth to open the forced
        # password-change modal immediately after a temporary-password reset.
        service.auth.admin.update_user_by_id(
            user_id,
            {
                "password": body.password,
                "user_metadata": {"must_change_password": True},
            },
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail="Could not generate a new temporary teacher login.",
        )
    return TemporaryPasswordResetResult(changed=True)


@router.put("/users/{user_id}", response_model=ChangedResult)
def update_user(
    user_id: str,
    body: TeacherUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Update a tenant teacher's identity and subject/course assignments."""
    require_institution_admin(profile)
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
    # Send only application-owned fields instead of echoing arbitrary legacy
    # Auth metadata back to the identity provider.
    updated_metadata = {
        "tenant_id": profile.tenant_id,
        "role": "teacher",
        "full_name": full_name,
        "must_change_password": bool(
            previous_metadata.get("must_change_password", False)
        ),
    }
    previous_course_id = previous_metadata.get("course_id")
    if previous_course_id:
        updated_metadata["course_id"] = previous_course_id

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
        replace_teacher_subjects(
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
        raise public_error(
            400,
            "We couldn't update this teacher. Check the account details and try again.",
            operation="update teacher",
            exception=exc,
        ) from exc

    return {"changed": True}


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


@router.get("/teachers/{teacher_id}/courses", response_model=list[TeacherCourseOut])
def list_teacher_courses(
    teacher_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Return courses derived from a teacher's explicit subject assignments."""
    require_institution_admin(profile)
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


@router.get("/courses/{course_id}/students", response_model=CourseRosterOut)
def list_course_students(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Return the tenant-scoped student roster for one course."""
    require_institution_admin(profile)
    service = get_service_client()
    course = _assert_tenant_course(
        service, course_id=course_id, tenant_id=profile.tenant_id
    )
    enrollments = _select_all(
        service,
        "enrollments",
        "id, profile_id",
        configure=lambda query: query.eq("tenant_id", profile.tenant_id).eq(
            "course_id", course_id
        ),
    )
    profile_ids = list({str(row["profile_id"]) for row in enrollments})
    students = []
    if profile_ids:
        students = _select_all(
            service,
            "profiles",
            "id, full_name",
            configure=lambda query: query.eq(
                "tenant_id", profile.tenant_id
            ).eq("role", "student").in_("id", profile_ids),
        )
    email_by_id = (
        _email_by_auth_user_id(
            service, {str(student["id"]) for student in students}
        )
        if students
        else {}
    )
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


@router.get("/admin/courses/{course_id}/impact", response_model=CourseImpact)
def get_course_impact(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> CourseImpact:
    """Describe everything a hard course deletion can remove or disconnect."""
    require_institution_admin(profile)
    service = get_service_client()
    _assert_tenant_course(service, course_id=course_id, tenant_id=profile.tenant_id)
    subjects = _select_all(
        service,
        "subjects",
        "id",
        configure=lambda item: item.eq("tenant_id", profile.tenant_id).eq(
            "course_id", course_id
        ),
    )
    subject_ids = [str(subject["id"]) for subject in subjects]
    enrollments = _select_all(
        service,
        "enrollments",
        "id, profile_id",
        configure=lambda item: item.eq("tenant_id", profile.tenant_id).eq(
            "course_id", course_id
        ),
    )
    enrolled_profile_ids = list({str(row["profile_id"]) for row in enrollments})
    students: list[dict] = []
    if enrolled_profile_ids:
        students = _select_all(
            service,
            "profiles",
            "id",
            configure=lambda item: item.eq("tenant_id", profile.tenant_id)
            .eq("role", "student")
            .in_("id", enrolled_profile_ids),
        )
    teacher_assignments: list[dict] = []
    quiz_sets: list[dict] = []
    documents: list[dict] = []
    if subject_ids:
        teacher_assignments = _select_all(
            service,
            "teacher_subjects",
            "id",
            configure=lambda item: item.eq("tenant_id", profile.tenant_id).in_(
                "subject_id", subject_ids
            ),
        )
        quiz_sets = _select_all(
            service,
            "quiz_sets",
            "id",
            configure=lambda item: item.eq("tenant_id", profile.tenant_id).in_(
                "subject_id", subject_ids
            ),
        )
        chapters = _select_all(
            service,
            "chapters",
            "id",
            configure=lambda item: item.eq("tenant_id", profile.tenant_id).in_(
                "subject_id", subject_ids
            ),
        )
        chapter_ids = [str(chapter["id"]) for chapter in chapters]
        if chapter_ids:
            documents = _select_all(
                service,
                "documents",
                "id",
                configure=lambda item: item.eq("tenant_id", profile.tenant_id).in_(
                    "chapter_id", chapter_ids
                ),
            )
    return CourseImpact(
        subjects=len(subjects),
        students=len(students),
        teacher_assignments=len(teacher_assignments),
        quiz_sets=len(quiz_sets),
        documents=len(documents),
    )


# ── Super-admin: institution admins ──────────────────────────────────────────
class AdminCreate(BaseModel):
    full_name: str
    email: str
    password: str = Field(min_length=12, max_length=128)
    tenant_id: str


@router.get("/tenants", response_model=list[TenantOption])
def list_tenants(
    page: int = 1,
    page_size: int = ADMIN_DIRECTORY_PAGE_SIZE,
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Institutions (tenants) the super-admin can assign an admin to."""
    require_super_admin(profile)
    if page < 1 or page_size < 1 or page_size > ADMIN_DIRECTORY_PAGE_SIZE:
        raise HTTPException(status_code=400, detail="Invalid directory page.")
    service = get_service_client()
    start = (page - 1) * page_size
    return (
        service.table("tenants")
        .select("id, name, subdomain")
        .order("name")
        .range(start, start + page_size - 1)
        .execute()
        .data
        or []
    )


@router.get("/admins", response_model=list[InstitutionAdminOut])
def list_admins(
    page: int = 1,
    page_size: int = ADMIN_DIRECTORY_PAGE_SIZE,
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Every institution admin across the platform, with their institution."""
    require_super_admin(profile)
    if page < 1 or page_size < 1 or page_size > ADMIN_DIRECTORY_PAGE_SIZE:
        raise HTTPException(status_code=400, detail="Invalid directory page.")
    service = get_service_client()
    start = (page - 1) * page_size
    admins = (
        service.table("profiles")
        .select("id, full_name, tenant_id")
        .eq("role", "institution_admin")
        .order("id")
        .range(start, start + page_size - 1)
        .execute()
        .data
        or []
    )
    if not admins:
        return []
    email_by_id = _email_by_auth_user_id(
        service, {str(admin["id"]) for admin in admins}
    )
    tenant_ids = list({str(admin["tenant_id"]) for admin in admins})
    tenants = _select_all(
        service,
        "tenants",
        "id, name, subdomain",
        configure=lambda query: query.in_("id", tenant_ids),
    )
    tname = {t["id"]: t["name"] for t in tenants}
    tenant_subdomain = {t["id"]: t["subdomain"] for t in tenants}
    offerings = institution_offerings_by_tenant(service, tenant_ids)
    return [
        {
            "id": a["id"],
            "full_name": a["full_name"],
            "email": email_by_id.get(a["id"]),
            "institution": tname.get(a["tenant_id"], "?"),
            "subdomain": tenant_subdomain.get(a["tenant_id"], ""),
            "courses": [
                course["name"] for course in offerings.get(str(a["tenant_id"]), [])
            ],
            "course_count": len(offerings.get(str(a["tenant_id"]), [])),
        }
        for a in admins
    ]


@router.post("/admins", response_model=CreatedResult)
def create_admin(
    body: AdminCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin creates an institution admin (aka principal) for a tenant."""
    require_super_admin(profile)
    _validate_temporary_password(body.password)
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
                    "_backend_provisioning_intent": True,
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
            try:
                _rollback_provisioned_user(service, created.user.id)
            except Exception as rollback_exc:  # noqa: BLE001
                raise public_error(
                    500,
                    "The administrator could not be created cleanly and requires operator review.",
                    operation="roll back institution administrator",
                    exception=rollback_exc,
                ) from exc
        raise auth_provisioning_error(
            exc,
            operation="create institution administrator",
        ) from exc

    return {"created": True}


@router.delete("/platform/admins/{user_id}", response_model=DeletedResult)
def remove_admin(
    user_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin removes an institution admin (auth user + profile)."""
    require_super_admin(profile)
    service = get_service_client()

    target = (
        service.table("profiles")
        .select("id, role, tenant_id")
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

    # Erase personal data first, delete the Auth identity, then clear the profile
    # row in case the FK is not configured to cascade.
    try:
        erase_account_data(
            service,
            user_id=user_id,
            tenant_id=str(target.data["tenant_id"]),
        )
        service.auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            400,
            "We couldn't remove this institution administrator. Please try again.",
            operation="remove institution administrator",
            exception=exc,
        ) from exc
    service.table("profiles").delete().eq("id", user_id).execute()

    return {"deleted": True}


@router.post(
    "/platform/admins/{user_id}/temporary-password",
    response_model=TemporaryPasswordResetResult,
)
def reset_admin_temporary_password(
    user_id: str,
    body: TemporaryPasswordReset,
    profile: CurrentProfile = Depends(get_current_profile),
) -> TemporaryPasswordResetResult:
    """Replace an institution admin password without ever returning plaintext."""
    require_super_admin(profile)
    _validate_temporary_password(body.password)
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
        raise HTTPException(
            status_code=400,
            detail="That user is not an institution admin.",
        )

    try:
        updated_profile = (
            service.table("profiles")
            .update({"must_change_password": True})
            .eq("id", user_id)
            .eq("role", "institution_admin")
            .execute()
        )
        if not updated_profile.data:
            raise RuntimeError("The administrator profile could not be updated.")
        # See the teacher reset path above: the frontend must receive this
        # flag from Auth as well as the backend enforcing it from profiles.
        service.auth.admin.update_user_by_id(
            user_id,
            {
                "password": body.password,
                "user_metadata": {"must_change_password": True},
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            503,
            "We couldn't reset this administrator's login. Please try again.",
            operation="reset institution administrator password",
            exception=exc,
        ) from exc

    return TemporaryPasswordResetResult(changed=True)


# ── Analytics ────────────────────────────────────────────────────────────────
@router.get("/admin/stats", response_model=InstitutionStats)
def institution_stats(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_institution_admin(profile)
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
async def institution_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Rich, real-data overview for the institution-admin dashboard: people counts,
    content counts, institution-wide accuracy, a 14-day activity trend, top
    courses by enrolment, the question review pipeline, and recent quiz sets.
    """
    from collections import Counter
    from datetime import date, timedelta

    require_institution_admin(profile)
    t = profile.tenant_id

    # Fetch through the shared helper so database failures are surfaced rather
    # than converted into valid-looking zero metrics.
    data = await _gather(
        {
            "profiles": lambda client: _select_all(client, "profiles", "id, role", configure=lambda item: item.eq("tenant_id", t)),
            "courses": lambda client: _select_all(client, "courses", "id, name", configure=lambda item: item.eq("tenant_id", t)),
            "subjects": lambda client: _select_all(client, "subjects", "id", configure=lambda item: item.eq("tenant_id", t)),
            "documents": lambda client: _select_all(client, "documents", "id", configure=lambda item: item.eq("tenant_id", t)),
            "quiz_sets": lambda client: _select_all(client, "quiz_sets", "id, title, status, created_at", configure=lambda item: item.eq("tenant_id", t)),
            "questions": lambda client: _select_all(client, "questions", "id, review_status", configure=lambda item: item.eq("tenant_id", t)),
            "variants": lambda client: _select_all(client, "quiz_variants", "id, total_marks", configure=lambda item: item.eq("tenant_id", t)),
            "attempts": lambda client: _select_all(client, "quiz_attempts", "id, status, total_score, variant_id, submitted_at", configure=lambda item: item.eq("tenant_id", t)),
            "enrollments": lambda client: _select_all(client, "enrollments", "id, profile_id, course_id", configure=lambda item: item.eq("tenant_id", t)),
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
    quiz_sets.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    published = sum(1 for q in quiz_sets if q["status"] == "published")
    draft = sum(1 for q in quiz_sets if q["status"] == "draft")

    # Question review pipeline
    questions = data["questions"]
    pipeline = {"pending_review": 0, "approved": 0, "rejected": 0, "needs_edit": 0}
    for q in questions:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    # Attempts -> institution accuracy + activity trend
    variants = data["variants"]
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    attempts = data["attempts"]
    graded = [a for a in attempts if a["status"] == "graded"]
    total_score = 0.0
    total_maximum = 0.0
    for a in graded:
        m = var_marks.get(a["variant_id"])
        if m:
            maximum = float(m)
            total_score += max(0.0, min(maximum, float(a.get("total_score") or 0)))
            total_maximum += maximum
    accuracy = round(total_score / total_maximum * 100) if total_maximum else 0

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
    student_ids = {p["id"] for p in profiles if p["role"] == "student"}
    enr_counts = Counter(
        e["course_id"] for e in enrollments if e.get("profile_id") in student_ids
    )
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
        "attempts": len(graded),
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
    admins: int
    active_week: int
    inactive_students: int
    at_risk: int
    avg_accuracy: int
    graded_attempts: int
    published_quizzes: int
    quiz_sets: int
    courses: int
    subjects: int
    documents: int
    draft_quizzes: int
    questions: int


class AnalyticsTrend(BaseModel):
    attempts_last7: int
    attempts_prev7: int
    delta: int
    percentage_change: float
    has_trend: bool


class AnalyticsPipeline(BaseModel):
    pending_review: int
    approved: int
    rejected: int
    needs_edit: int


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


async def _gather(thunks: dict[str, Callable[[object], object]]) -> dict:
    """Run Supabase reads concurrently and propagate failures to the UI.

    The process-wide client uses httpx's thread-safe HTTP/1.1 connection pool,
    so these worker threads can share it without HTTP/2 multiplexing failures.
    Errors still propagate instead of being converted into false zero values.
    """

    async def run(key: str, thunk: Callable[[object], object]):
        return key, await asyncio.to_thread(lambda: thunk(get_service_client()))

    results = await asyncio.gather(*(run(key, thunk) for key, thunk in thunks.items()))
    return dict(results)


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
    review_backlog = pipeline["pending_review"] + pipeline.get("needs_edit", 0)
    if review_backlog > 0:
        out.append(
            {
                "severity": "critical" if review_backlog >= 10 else "warn",
                "title": f"{review_backlog} questions need review or edits",
                "detail": "Pending and needs-edit questions can't be published to students.",
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
async def institution_analytics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> InstitutionAnalyticsResponse:
    """Data-analyst-style analytics for the institution admin: engagement, student
    outcomes, course performance, teacher activity, and plain-language findings.
    Pure database aggregation — no AI/ML."""
    from collections import Counter, defaultdict
    from datetime import date, datetime, timedelta

    require_institution_admin(profile)
    t = profile.tenant_id

    data = await _gather(
        {
            "profiles": lambda client: _select_all(client, "profiles", "id, role, full_name", configure=lambda item: item.eq("tenant_id", t)),
            "courses": lambda client: _select_all(client, "courses", "id, name", configure=lambda item: item.eq("tenant_id", t)),
            "subjects": lambda client: _select_all(client, "subjects", "id, course_id", configure=lambda item: item.eq("tenant_id", t)),
            "quiz_sets": lambda client: _select_all(client, "quiz_sets", "id, title, status, created_by, subject_id, created_at", configure=lambda item: item.eq("tenant_id", t)),
            "questions": lambda client: _select_all(client, "questions", "id, review_status, source, type, reviewed_by", configure=lambda item: item.eq("tenant_id", t)),
            "variant_questions": lambda client: _select_all(client, "quiz_variant_questions", "variant_id, question_id", configure=lambda item: item.eq("tenant_id", t)),
            "variants": lambda client: _select_all(client, "quiz_variants", "id, total_marks, quiz_set_id", configure=lambda item: item.eq("tenant_id", t)),
            "attempts": lambda client: _select_all(client, "quiz_attempts", "id, student_id, status, total_score, variant_id, submitted_at", configure=lambda item: item.eq("tenant_id", t)),
            "enrollments": lambda client: _select_all(client, "enrollments", "id, profile_id, course_id", configure=lambda item: item.eq("tenant_id", t)),
            "documents": lambda client: _select_all(client, "documents", "id", configure=lambda item: item.eq("tenant_id", t)),
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
    documents = data["documents"]

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
    quizset_scores: dict = defaultdict(lambda: [0.0, 0.0])
    course_scores: dict = defaultdict(lambda: [0.0, 0.0])
    student_scores: dict = defaultdict(lambda: [0.0, 0.0])
    student_quiz_pcts: dict = defaultdict(lambda: defaultdict(list))
    student_quiz_scores: dict = defaultdict(
        lambda: defaultdict(lambda: [0.0, 0.0])
    )
    student_quiz_last: dict = defaultdict(dict)
    quizset_attempts: Counter = Counter()
    course_attempts: Counter = Counter()
    graded_student_ids: set[str] = set()
    active_ids: set = set()
    attempts_last7 = attempts_prev7 = 0
    for a in graded:
        p = pct(a)
        sid = a.get("student_id")
        sa = a.get("submitted_at")
        quiz_set_id = var_quizset.get(a.get("variant_id"))
        course_id = quizset_course.get(quiz_set_id)
        if sid:
            graded_student_ids.add(sid)
        if quiz_set_id:
            quizset_attempts[quiz_set_id] += 1
        if course_id:
            course_attempts[course_id] += 1
        if p is not None:
            max_score = float(var_marks[a["variant_id"]])
            score = max(0.0, min(max_score, float(a.get("total_score") or 0)))
            if sid:
                stu_pcts[sid].append(p)
                student_scores[sid][0] += score
                student_scores[sid][1] += max_score
            if quiz_set_id:
                quizset_scores[quiz_set_id][0] += score
                quizset_scores[quiz_set_id][1] += max_score
                if sid:
                    student_quiz_pcts[sid][quiz_set_id].append(p)
                    student_quiz_scores[sid][quiz_set_id][0] += score
                    student_quiz_scores[sid][quiz_set_id][1] += max_score
                    if sa and sa > student_quiz_last[sid].get(quiz_set_id, ""):
                        student_quiz_last[sid][quiz_set_id] = sa
            if course_id:
                course_scores[course_id][0] += score
                course_scores[course_id][1] += max_score
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
    inactive_students = [s for s in students if s["id"] not in graded_student_ids]

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
    student_ids = {student["id"] for student in students}
    enr_by_course = Counter(
        e["course_id"] for e in enrollments if e.get("profile_id") in student_ids
    )
    published_by_course = Counter(
        quizset_course.get(q["id"]) for q in quiz_sets if q["status"] == "published"
    )
    pending_question_ids = {
        q["id"]
        for q in questions
        if q.get("review_status") in {"pending_review", "needs_edit"}
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
                "attempts": course_attempts.get(c["id"], 0),
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
    teacher_scores: dict = defaultdict(lambda: [0.0, 0.0])
    teacher_attempts: Counter = Counter()
    for quiz_set in quiz_sets:
        teacher_id = quiz_set.get("created_by")
        if teacher_id:
            teacher_attempts[teacher_id] += quizset_attempts.get(quiz_set["id"], 0)
            teacher_scores[teacher_id][0] += quizset_scores[quiz_set["id"]][0]
            teacher_scores[teacher_id][1] += quizset_scores[quiz_set["id"]][1]

    active_since = datetime.now(timezone.utc) - timedelta(days=30)

    def teacher_is_active(value: str | None) -> bool:
        if not value:
            return False
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) >= active_since
        except ValueError:
            return False

    teacher_activity = sorted(
        [
            {
                "teacher_id": tt["id"],
                "name": tt.get("full_name") or "—",
                "quiz_sets": qs_by_teacher.get(tt["id"], {}).get("sets", 0),
                "published": qs_by_teacher.get(tt["id"], {}).get("published", 0),
                "approved": approved_by_teacher.get(tt["id"], 0),
                "attempts": teacher_attempts.get(tt["id"], 0),
                "accuracy": (
                    round(
                        teacher_scores[tt["id"]][0]
                        / teacher_scores[tt["id"]][1]
                        * 100
                    )
                    if teacher_scores[tt["id"]][1]
                    else 0
                ),
                "last_quiz_created": qs_by_teacher.get(tt["id"], {}).get(
                    "last_quiz_created"
                ),
                "is_active": teacher_is_active(
                    qs_by_teacher.get(tt["id"], {}).get("last_quiz_created")
                ),
            }
            for tt in teachers
        ],
        key=lambda x: (-x["attempts"], -x["quiz_sets"], x["name"].lower()),
    )

    pipeline = {"pending_review": 0, "approved": 0, "rejected": 0, "needs_edit": 0}
    for q in questions:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    trend = {
        "attempts_last7": attempts_last7,
        "attempts_prev7": attempts_prev7,
        "delta": attempts_last7 - attempts_prev7,
        "percentage_change": (
            round((attempts_last7 - attempts_prev7) / attempts_prev7 * 100, 1)
            if attempts_prev7
            else (100.0 if attempts_last7 else 0.0)
        ),
        "has_trend": (attempts_last7 + attempts_prev7) > 0,
    }
    summary = {
        "students": len(students),
        "teachers": len(teachers),
        "admins": sum(1 for p in profiles if p["role"] == "institution_admin"),
        "active_week": len(active_ids),
        "inactive_students": len(inactive_students),
        "at_risk": len(at_risk),
        "avg_accuracy": avg_accuracy,
        "graded_attempts": len(graded),
        "published_quizzes": sum(1 for q in quiz_sets if q["status"] == "published"),
        "quiz_sets": len(quiz_sets),
        "courses": len(courses),
        "subjects": len(subjects),
        "documents": len(documents),
        "draft_quizzes": sum(1 for q in quiz_sets if q["status"] == "draft"),
        "questions": len(questions),
    }

    return InstitutionAnalyticsResponse(**{
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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


@router.get("/platform/stats", response_model=PlatformStatsResponse)
def platform_stats(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    require_super_admin(profile)
    overview = _rpc_json(get_service_client(), "platform_overview_metrics")
    per_tenant = [
        {
            "id": tenant["id"],
            "name": tenant["name"],
            "teachers": tenant["teachers"],
            "students": tenant["students"],
        }
        for tenant in sorted(
            overview["institutions_table"],
            key=lambda tenant: (tenant.get("name") or "").lower(),
        )
    ]

    return {
        "institutions": overview["institutions"],
        "total_teachers": overview["teachers"],
        "total_students": overview["students"],
        "per_institution": per_tenant,
    }


@router.get("/platform/overview", response_model=PlatformOverviewResponse)
async def platform_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Cross-tenant command-center overview for the super admin: platform-wide
    people/content counts, question approval rate (the ≥70% quality KPI),
    platform accuracy, a 14-day activity trend, and a per-institution table
    with each institution's key numbers + health. All real data.
    """
    require_super_admin(profile)

    def load_overview() -> dict:
        service = get_service_client()
        overview = _rpc_json(service, "platform_overview_metrics")
        institution_rows = overview.get("institutions_table") or []
        tenant_ids = [str(row["id"]) for row in institution_rows]
        offerings = institution_offerings_by_tenant(service, tenant_ids)
        branding_rows = (
            service.table("tenants")
            .select("id, logo_url, logo_filename, primary_color, feature_flags")
            .in_("id", tenant_ids)
            .execute()
            .data
            or []
        ) if tenant_ids else []
        branding_by_tenant = {str(row["id"]): row for row in branding_rows}
        enriched_rows: list[dict] = []
        for row in institution_rows:
            tenant_courses = offerings.get(str(row["id"]), [])
            branding = branding_by_tenant.get(str(row["id"]), {})
            browser_logo = _signed_logo_url(branding.get("logo_url"))
            enriched_rows.append(
                {
                    **row,
                    "courses": [course["name"] for course in tenant_courses],
                    **offering_counts(tenant_courses),
                    "logo_url": browser_logo,
                    "logo_filename": branding.get("logo_filename"),
                    "primary_color": branding.get("primary_color") or "#2E8857",
                    "feature_flags": normalize_feature_flags(branding.get("feature_flags")),
                }
            )
        return {**overview, "institutions_table": enriched_rows}

    return await asyncio.to_thread(load_overview)


@router.get(
    "/platform/tenants/{tenant_id}/offerings",
    response_model=TenantOfferings,
)
def platform_tenant_offerings(
    tenant_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Return an institution's operational Course -> Level -> Subject tree."""
    require_super_admin(profile)
    service = get_service_client()
    tenant = (
        service.table("tenants")
        .select("id")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    if tenant is None or not tenant.data:
        raise HTTPException(status_code=404, detail="Institution not found.")
    offerings = institution_offerings_by_tenant(service, [tenant_id])
    return {"tenant_id": tenant_id, "courses": offerings.get(tenant_id, [])}


# ── Super-admin: onboard a new institution (tenant) ──────────────────────────
class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    subdomain: str
    plan_tier: Literal["free", "starter", "growth", "enterprise"] = "free"
    logo_data: str | None = Field(default=None, max_length=1_500_000)
    logo_content_type: str | None = None
    logo_filename: str | None = Field(default=None, max_length=255)
    primary_color: str = "#2E8857"
    # Optional first institution admin created alongside the tenant.
    admin_full_name: str | None = None
    admin_email: str | None = None
    admin_password: str | None = Field(default=None, min_length=12, max_length=128)
    catalog_subject_ids: list[UUID] = Field(default_factory=list, max_length=175)

    @field_validator("primary_color")
    @classmethod
    def validate_primary_color(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 7 or value[0] != "#" or any(
            character not in "0123456789ABCDEF" for character in value[1:]
        ):
            raise ValueError("Brand color must be a six-digit hex color.")
        return value


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    subdomain: str | None = Field(
        default=None,
        max_length=INSTITUTION_SUBDOMAIN_MAX_LENGTH,
    )
    plan_tier: Literal["free", "starter", "growth", "enterprise"] | None = None
    is_active: bool | None = None
    logo_data: str | None = Field(default=None, max_length=1_500_000)
    logo_content_type: str | None = None
    logo_filename: str | None = Field(default=None, max_length=255)
    primary_color: str | None = None

    @field_validator("primary_color")
    @classmethod
    def validate_primary_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 7 or value[0] != "#" or any(
            character not in "0123456789ABCDEF" for character in value[1:]
        ):
            raise ValueError("Brand color must be a six-digit hex color.")
        return value


def _decode_institution_logo(
    *,
    logo_data: str | None,
    content_type: str | None,
    filename: str | None,
) -> tuple[bytes, str, str] | None:
    """Validate a small PNG/JPEG logo and return bytes, MIME type and extension."""
    supplied = [logo_data, content_type, filename]
    if not any(supplied):
        return None
    if not logo_data or not content_type or not filename:
        raise HTTPException(
            status_code=400,
            detail="Logo file, filename, and content type are required together.",
        )
    if content_type not in INSTITUTION_LOGO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Institution logo must be a PNG or JPEG image.",
        )
    payload = (
        logo_data.split(",", 1)[1]
        if logo_data.startswith("data:") and "," in logo_data
        else logo_data
    )
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Institution logo is not valid image data.",
        ) from exc
    if not decoded or len(decoded) > INSTITUTION_LOGO_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Institution logo must be no larger than 1 MB.",
        )
    is_png = decoded.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = decoded.startswith(b"\xff\xd8\xff")
    if (content_type == "image/png" and not is_png) or (
        content_type == "image/jpeg" and not is_jpeg
    ):
        raise HTTPException(
            status_code=400,
            detail="Institution logo content does not match its file type.",
        )
    return decoded, content_type, INSTITUTION_LOGO_TYPES[content_type]


@router.post("/platform/tenants", response_model=InstitutionCreatedResult)
def onboard_institution(
    body: TenantCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Super-admin onboards a new institution (Stage 1 of the workflow)."""
    require_super_admin(profile)
    service = get_service_client()
    catalog_subject_ids = list(dict.fromkeys(map(str, body.catalog_subject_ids)))
    if catalog_subject_ids:
        active_subject_ids = active_catalog_subject_ids(service, catalog_subject_ids)
        if active_subject_ids != set(catalog_subject_ids):
            raise HTTPException(
                status_code=400,
                detail="One or more selected course offerings are no longer available.",
            )
    logo = _decode_institution_logo(
        logo_data=body.logo_data,
        content_type=body.logo_content_type,
        filename=body.logo_filename,
    )

    name = body.name.strip()
    subdomain = _normalize_institution_subdomain(body.subdomain)
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
    if body.admin_password:
        _validate_temporary_password(body.admin_password)
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
                    "primary_color": body.primary_color,
                }
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            400,
            "We couldn't create this institution. Check the details and try again.",
            operation="create institution",
            exception=exc,
        ) from exc
    tenant_id = created.data[0]["id"]
    logo_path: str | None = None

    if logo is not None:
        logo_bytes, logo_content_type, logo_extension = logo
        logo_path = f"tenant-logos/{tenant_id}/{uuid4().hex}.{logo_extension}"
        try:
            upload_bytes(logo_path, logo_bytes, logo_content_type)
            logo_update = (
                service.table("tenants")
                .update({"logo_url": logo_path, "logo_filename": body.logo_filename})
                .eq("id", tenant_id)
                .execute()
            )
            if not logo_update.data:
                raise RuntimeError("Tenant logo path was not persisted.")
        except Exception as exc:  # noqa: BLE001
            if logo_path:
                try:
                    delete_bytes(logo_path)
                except Exception:  # noqa: BLE001
                    pass
            try:
                _rollback_tenant(service, tenant_id)
            except Exception as rollback_exc:  # noqa: BLE001
                raise public_error(
                    500,
                    "Institution setup requires operator review.",
                    operation="roll back institution logo setup",
                    exception=rollback_exc,
                ) from exc
            raise public_error(
                400,
                "We couldn't store the institution logo. Please try another image.",
                operation="store institution logo",
                exception=exc,
            ) from exc

    provisioned_user_id: str | None = None
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
                        "_backend_provisioning_intent": True,
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
            provisioned_user_id = str(u.user.id)
        except Exception as exc:  # noqa: BLE001
            rollback_error = None
            if "u" in locals() and u.user:
                try:
                    _rollback_provisioned_user(service, u.user.id)
                except Exception as cleanup_exc:  # noqa: BLE001
                    rollback_error = cleanup_exc
            try:
                _rollback_tenant(service, tenant_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                rollback_error = rollback_error or cleanup_exc
            if logo_path:
                try:
                    delete_bytes(logo_path)
                except Exception as cleanup_exc:  # noqa: BLE001
                    rollback_error = rollback_error or cleanup_exc
            if rollback_error is not None:
                raise public_error(
                    500,
                    "Institution setup could not be completed cleanly. The tenant has been disabled for operator review.",
                    operation="roll back institution onboarding",
                    exception=rollback_error,
                ) from exc
            raise auth_provisioning_error(
                exc,
                operation="create first institution administrator",
            ) from exc

    if catalog_subject_ids:
        try:
            for catalog_subject_id in catalog_subject_ids:
                provision_catalog_subject(
                    service,
                    tenant_id=str(tenant_id),
                    catalog_subject_id=catalog_subject_id,
                )
        except Exception as exc:  # noqa: BLE001
            rollback_error = None
            if provisioned_user_id:
                try:
                    _rollback_provisioned_user(service, provisioned_user_id)
                except Exception as cleanup_exc:  # noqa: BLE001
                    rollback_error = cleanup_exc
            try:
                _rollback_tenant(service, tenant_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                rollback_error = rollback_error or cleanup_exc
            if logo_path:
                try:
                    delete_bytes(logo_path)
                except Exception as cleanup_exc:  # noqa: BLE001
                    rollback_error = rollback_error or cleanup_exc
            if rollback_error is not None:
                raise public_error(
                    500,
                    "Institution setup could not be completed cleanly. The tenant has been disabled for operator review.",
                    operation="roll back institution course setup",
                    exception=rollback_error,
                ) from exc
            raise public_error(
                400,
                "The institution was not created because its course offerings could not be saved.",
                operation="provision institution course offerings",
                exception=exc,
            ) from exc

    return {"created": True, "tenant_id": tenant_id}


@router.patch("/platform/tenants/{tenant_id}", response_model=TenantDetails)
def update_institution(
    tenant_id: str,
    body: TenantUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Update safe tenant lifecycle fields; permanent deletion is intentionally absent."""
    require_super_admin(profile)
    logo = _decode_institution_logo(
        logo_data=body.logo_data,
        content_type=body.logo_content_type,
        filename=body.logo_filename,
    )
    changes = body.model_dump(
        exclude_none=True,
        exclude={"logo_data", "logo_content_type", "logo_filename"},
    )
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(status_code=400, detail="Institution name is required.")
    if "subdomain" in changes:
        changes["subdomain"] = _normalize_institution_subdomain(
            changes["subdomain"]
        )
    if not changes and logo is None:
        raise HTTPException(status_code=400, detail="Choose at least one field to update.")

    service = get_service_client()
    existing = (
        service.table("tenants")
        .select(
            "id, subdomain, logo_url, logo_filename, primary_color, feature_flags"
        )
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    if existing is None or not existing.data:
        raise HTTPException(status_code=404, detail="Institution not found.")
    if (
        "subdomain" in changes
        and changes["subdomain"] != existing.data.get("subdomain")
    ):
        duplicate = (
            service.table("tenants")
            .select("id")
            .eq("subdomain", changes["subdomain"])
            .execute()
            .data
            or []
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="That institution access URL is already in use.",
            )
    previous_logo_path = existing.data.get("logo_url")
    new_logo_path: str | None = None
    if logo is not None:
        logo_bytes, logo_content_type, logo_extension = logo
        new_logo_path = f"tenant-logos/{tenant_id}/{uuid4().hex}.{logo_extension}"
        try:
            upload_bytes(new_logo_path, logo_bytes, logo_content_type)
        except Exception as exc:  # noqa: BLE001
            raise public_error(
                400,
                "We couldn't store the institution logo. Please try another image.",
                operation="replace institution logo",
                exception=exc,
            ) from exc
        changes["logo_url"] = new_logo_path
        changes["logo_filename"] = body.logo_filename
    try:
        updated = (
            service.table("tenants")
            .update(changes)
            .eq("id", tenant_id)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        if new_logo_path:
            try:
                delete_bytes(new_logo_path)
            except Exception:  # noqa: BLE001
                pass
        raise public_error(
            400,
            "We couldn't update this institution. Please try again.",
            operation="update institution",
            exception=exc,
        ) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Institution not found.")
    if (
        new_logo_path
        and isinstance(previous_logo_path, str)
        and previous_logo_path.startswith("tenant-logos/")
    ):
        try:
            delete_bytes(previous_logo_path)
        except Exception:  # noqa: BLE001
            # The new logo is already committed; stale-file cleanup must not
            # turn a successful settings update into a user-facing failure.
            pass
    row = updated[0]
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "subdomain": row["subdomain"],
        "plan_tier": row["plan_tier"],
        "is_active": row["is_active"],
        "created_at": row.get("created_at"),
        "logo_url": _signed_logo_url(row.get("logo_url")),
        "logo_filename": row.get("logo_filename"),
        "primary_color": row.get("primary_color") or "#2E8857",
        "feature_flags": normalize_feature_flags(row.get("feature_flags")),
    }


# ── Super-admin: global question bank (cross-tenant, grouped by course) ───────
@router.get("/platform/question-bank", response_model=QuestionBankResponse)
def platform_question_bank(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Every question on the platform, grouped by course. Real counts only."""
    require_super_admin(profile)
    return _rpc_json(get_service_client(), "platform_question_bank_metrics")


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
@router.get("/platform/ai-monitoring", response_model=AiMonitoringResponse)
def platform_ai_monitoring(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """AI generation health across the platform: volume, quality by type, pipeline."""
    from datetime import datetime, timezone

    require_super_admin(profile)
    payload = _rpc_json(get_service_client(), "platform_ai_monitoring_metrics")
    payload["findings"] = _build_findings(
        total_generated=payload["total_generated"],
        status=payload["pipeline"],
        approval_rate=payload["approval_rate"],
        types_out=payload["by_type"],
        signals=payload["signals"],
        trend=payload["trend"],
        failures_14d=payload["failures_14d"],
    )
    payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return payload


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
async def admin_quiz_sets(
    profile: CurrentProfile = Depends(get_current_profile),
    teacher_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[AdminQuizSet]:
    """
    Every quiz set in the institution, enriched with course/subject/teacher and a
    question/review counts and graded-attempt performance.

    Fetched as a single embedded query (Supabase/PostgREST foreign-key
    embedding) instead of several sequential round trips — Postgres resolves
    every join server-side in one request.
    """
    require_institution_admin(profile)
    if page < 1 or page_size < 1 or page_size > ADMIN_QUIZ_SET_PAGE_SIZE_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                "page must be positive and page_size must be between 1 and "
                f"{ADMIN_QUIZ_SET_PAGE_SIZE_MAX}."
            ),
        )
    t = profile.tenant_id
    start = (page - 1) * page_size

    def _fetch(client):
        q = (
            client.table("quiz_sets")
            .select(
                "id, title, status, subject_id, created_by, created_at, published_at, "
                "subjects(name, course_id, courses(name)), "
                "profiles!quiz_sets_created_by_fkey(full_name), "
                "quiz_variants(id, total_marks, "
                "quiz_variant_questions(question_id, questions(review_status)), "
                "quiz_attempts(total_score, submitted_at, status))"
            )
            .eq("tenant_id", t)
        )
        if teacher_id:
            q = q.eq("created_by", teacher_id)
        return (
            q.order("created_at", desc=True)
            .range(start, start + page_size - 1)
            .execute()
            .data
            or []
        )

    sets = await asyncio.to_thread(lambda: _fetch(get_service_client()))

    out: list[AdminQuizSet] = []
    for s in sets:
        sub = s.get("subjects")
        teacher = s.get("profiles")
        variants = s.get("quiz_variants") or []

        question_ids: set[str] = set()
        review_counter: Counter = Counter()
        attempts_count = 0
        score_sum = 0.0
        marks_sum = 0.0
        last_attempted_at = None
        for v in variants:
            maximum = float(v.get("total_marks") or 0)
            for vq in v.get("quiz_variant_questions") or []:
                qid = vq["question_id"]
                if qid not in question_ids:
                    question_ids.add(qid)
                    q_row = vq.get("questions") or {}
                    review_counter[q_row.get("review_status")] += 1
            for a in v.get("quiz_attempts") or []:
                if a.get("status") != "graded":
                    continue
                attempts_count += 1
                submitted_at = a.get("submitted_at")
                if submitted_at and (
                    last_attempted_at is None or submitted_at > last_attempted_at
                ):
                    last_attempted_at = submitted_at
                if maximum > 0:
                    score_sum += max(0.0, min(maximum, float(a.get("total_score") or 0)))
                    marks_sum += maximum

        out.append(
            AdminQuizSet(
                id=str(s["id"]),
                title=s["title"],
                status=s["status"],
                subject=sub["name"] if sub else None,
                subject_id=str(s["subject_id"]) if s.get("subject_id") else None,
                course=(sub.get("courses") or {}).get("name") if sub else None,
                course_id=str(sub["course_id"]) if sub and sub.get("course_id") else None,
                teacher=teacher.get("full_name") if teacher else None,
                teacher_id=str(s["created_by"]) if s.get("created_by") else None,
                questions=len(question_ids),
                attempts_count=attempts_count,
                avg_accuracy=round(max(0, min(100, score_sum / marks_sum * 100)), 1)
                if marks_sum
                else 0,
                created_at=s.get("created_at"),
                published_at=s.get("published_at"),
                last_attempted_at=last_attempted_at,
                review_status=ReviewStatusCounts(
                    pending=review_counter.get("pending_review", 0),
                    approved=review_counter.get("approved", 0),
                    rejected=review_counter.get("rejected", 0),
                    needs_edit=review_counter.get("needs_edit", 0),
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
async def admin_teacher_analytics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> TeacherAnalyticsResponse:
    """Tenant-wide faculty activity, engagement, and student outcomes.

    Two independent queries run concurrently: the full teacher roster (so a
    teacher with zero quizzes still appears) and every quiz set with its
    course/variant/attempt tree embedded in one round trip each (so a quiz
    set orphaned by a deleted teacher — migration 20's created_by -> null —
    still counts toward the tenant-wide totals, just not toward any
    individual teacher's row).
    """
    require_institution_admin(profile)
    tenant_id = profile.tenant_id

    def _fetch_teachers(client):
        return (
            client.table("profiles")
            .select("id, full_name")
            .eq("tenant_id", tenant_id)
            .eq("role", "teacher")
            .execute()
            .data
            or []
        )

    def _fetch_quiz_sets(client):
        return (
            client.table("quiz_sets")
            .select(
                "id, status, created_by, created_at, subject_id, "
                "subjects(course_id, courses(name)), "
                "quiz_variants(id, total_marks, quiz_attempts(total_score, status))"
            )
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )

    teachers, quiz_sets = await asyncio.gather(
        asyncio.to_thread(lambda: _fetch_teachers(get_service_client())),
        asyncio.to_thread(lambda: _fetch_quiz_sets(get_service_client())),
    )

    def _quiz_set_stats(qs: dict) -> tuple[int, float, float]:
        """Returns (attempts_count, score_sum, marks_sum) for one quiz set."""
        attempts_count = 0
        score_sum = 0.0
        marks_sum = 0.0
        for v in qs.get("quiz_variants") or []:
            maximum = float(v.get("total_marks") or 0)
            for a in v.get("quiz_attempts") or []:
                if a.get("status") != "graded":
                    continue
                attempts_count += 1
                if maximum > 0:
                    score_sum += max(0.0, min(maximum, float(a.get("total_score") or 0)))
                    marks_sum += maximum
        return attempts_count, score_sum, marks_sum

    sets_by_teacher: dict[str, list[dict]] = {}
    for qs in quiz_sets:
        created_by = qs.get("created_by")
        if created_by:
            sets_by_teacher.setdefault(created_by, []).append(qs)

    active_since = datetime.now(timezone.utc) - timedelta(days=30)
    details: list[TeacherAnalyticsDetail] = []
    for teacher in teachers:
        teacher_id = teacher["id"]
        teacher_sets = sets_by_teacher.get(teacher_id, [])

        course_names: set[str] = set()
        created_values: list[str] = []
        quiz_sets_published = 0
        attempts_count = 0
        score_sum = 0.0
        marks_sum = 0.0

        for qs in teacher_sets:
            if qs.get("status") == "published":
                quiz_sets_published += 1
            created_at = qs.get("created_at")
            if created_at:
                created_values.append(created_at)
            sub = qs.get("subjects")
            if sub:
                course = (sub.get("courses") or {}).get("name")
                if course:
                    course_names.add(course)
            a_count, s_sum, m_sum = _quiz_set_stats(qs)
            attempts_count += a_count
            score_sum += s_sum
            marks_sum += m_sum

        last_created_value = max(created_values) if created_values else None
        last_created = (
            datetime.fromisoformat(last_created_value.replace("Z", "+00:00"))
            if last_created_value
            else None
        )
        if last_created and last_created.tzinfo is None:
            last_created = last_created.replace(tzinfo=timezone.utc)

        details.append(
            TeacherAnalyticsDetail(
                teacher_id=str(teacher_id),
                teacher_name=teacher.get("full_name") or "Unnamed teacher",
                quiz_sets_created=len(teacher_sets),
                quiz_sets_published=quiz_sets_published,
                total_attempts=attempts_count,
                avg_accuracy=(
                    round(max(0, min(100, score_sum / marks_sum * 100)), 1)
                    if marks_sum
                    else 0
                ),
                last_quiz_created=last_created,
                is_active=bool(last_created and last_created >= active_since),
                course_names=sorted(course_names),
            )
        )

    details.sort(
        key=lambda row: (
            -row.total_attempts,
            -row.quiz_sets_created,
            row.teacher_name.lower(),
        )
    )

    # Tenant-wide totals come from the full quiz_sets list directly (not by
    # summing the per-teacher rows above), so an orphaned quiz set still
    # counts here even though it has no teacher row to attribute to.
    total_attempts_all = 0
    total_score_all = 0.0
    total_marks_all = 0.0
    for qs in quiz_sets:
        a_count, s_sum, m_sum = _quiz_set_stats(qs)
        total_attempts_all += a_count
        total_score_all += s_sum
        total_marks_all += m_sum

    return TeacherAnalyticsResponse(
        teachers=details,
        summary=TeacherAnalyticsSummary(
            total_teachers=len(details),
            active_teachers=sum(1 for row in details if row.is_active),
            avg_accuracy=(
                round(max(0, min(100, total_score_all / total_marks_all * 100)), 1)
                if total_marks_all
                else 0
            ),
            total_quiz_sets=len(quiz_sets),
            total_published=sum(
                1 for qs in quiz_sets if qs.get("status") == "published"
            ),
            total_attempts=total_attempts_all,
        ),
    )


@router.get("/admin/quiz-sets/{quiz_set_id}")
async def admin_quiz_set_detail(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Detailed question and student performance for one tenant quiz set.

    Fetched as a single embedded query — Postgres resolves the
    variant -> variant_questions -> questions and variant -> attempts ->
    student/answers joins server-side in one round trip.
    """
    require_institution_admin(profile)
    tenant_id = profile.tenant_id

    # This summary lookup doesn't depend on anything below — and is itself
    # already a single embedded query — so let it run concurrently with this
    # endpoint's own query instead of blocking on it up front.
    summary_task = asyncio.create_task(admin_quiz_sets(profile))

    def _fetch(client):
        return (
            client.table("quiz_variants")
            .select(
                "id, total_marks, "
                "quiz_variant_questions(question_id, "
                "questions(id, question_text, type, difficulty, review_status)), "
                "quiz_attempts(id, student_id, total_score, submitted_at, status, "
                "profiles(full_name), attempt_answers(question_id, is_correct))"
            )
            .eq("tenant_id", tenant_id)
            .eq("quiz_set_id", quiz_set_id)
            .execute()
            .data
            or []
        )

    variants = await asyncio.to_thread(lambda: _fetch(get_service_client()))

    variant_marks = {row["id"]: float(row.get("total_marks") or 0) for row in variants}

    question_by_id: dict[str, dict] = {}
    for row in variants:
        for vq in row.get("quiz_variant_questions") or []:
            q = vq.get("questions")
            if q:
                question_by_id[q["id"]] = q

    student_performance = []
    answer_counts: dict[str, dict[str, int]] = {}
    for row in variants:
        maximum = variant_marks.get(row["id"], 0)
        for attempt in row.get("quiz_attempts") or []:
            if attempt.get("status") != "graded":
                continue
            score = float(attempt.get("total_score") or 0)
            student = attempt.get("profiles") or {}
            student_performance.append(
                {
                    "attempt_id": str(attempt["id"]),
                    "student_id": str(attempt["student_id"]),
                    "student_name": student.get("full_name") or "Former student",
                    "score": score,
                    "max_score": maximum,
                    "accuracy": round(max(0, min(100, score / maximum * 100)), 1)
                    if maximum
                    else 0,
                    "submitted_at": attempt.get("submitted_at"),
                }
            )
            for answer in attempt.get("attempt_answers") or []:
                bucket = answer_counts.setdefault(
                    answer["question_id"], {"answered": 0, "correct": 0}
                )
                bucket["answered"] += 1
                if answer.get("is_correct") is True:
                    bucket["correct"] += 1
    student_performance.sort(
        key=lambda row: row.get("submitted_at") or "", reverse=True
    )

    summary = next(
        (row for row in await summary_task if row.id == quiz_set_id),
        None,
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Quiz set not found.")

    questions = list(question_by_id.values())
    by_type = Counter(question.get("type") or "unspecified" for question in questions)
    by_difficulty = Counter(
        question.get("difficulty") or "unspecified" for question in questions
    )

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
