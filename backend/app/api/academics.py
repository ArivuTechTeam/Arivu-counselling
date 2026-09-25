"""
Academic hierarchy API (courses / subjects).

  GET    /api/v1/public/courses?tenant_id=...  — UNauthenticated; signup dropdown.
  GET    /api/v1/courses                        — authenticated staff; teachers
                                                  see only mapped courses, while
                                                  admins see tenant courses.
  POST   /api/v1/courses                        — admin; create a course.
  POST   /api/v1/subjects                       — admin; create a subject.
  DELETE /api/v1/courses/{id}                    — admin; delete a course.
  DELETE /api/v1/subjects/{id}                   — admin; delete a subject.
  GET    /api/v1/catalog                         — global catalogue + offerings.
  POST   /api/v1/catalog/provision               — provision selected subjects.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_institution_admin, require_teacher
from app.lib.api_errors import public_error
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import rpc_json_value, select_all, select_all_in
from app.services.catalog import (
    active_catalog_subject_ids,
    catalog_tree,
    provision_catalog_subject,
)
from app.services.teacher_access import (
    replace_teacher_subjects,
    teacher_subject_ids,
)

router = APIRouter(prefix="/api/v1", tags=["academics"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _catalog_tenant(
    profile: CurrentProfile,
    requested_tenant_id: UUID | None,
    *,
    required: bool,
) -> str | None:
    if profile.role == "super_admin":
        if required and requested_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required for super-admin provisioning.",
            )
        return str(requested_tenant_id) if requested_tenant_id else None
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only super admins can manage catalogue offerings.",
    )


class CatalogSubjectOut(BaseModel):
    id: str
    name: str
    offered: bool


class CatalogLevelOut(BaseModel):
    id: str
    name: str
    subjects: list[CatalogSubjectOut]


class CatalogCourseOut(BaseModel):
    id: str
    code: str
    name: str
    levels: list[CatalogLevelOut]


class CatalogProvisionRequest(BaseModel):
    catalog_subject_ids: list[UUID] = Field(default_factory=list, max_length=175)


class CatalogProvisionResult(BaseModel):
    provisioned: int
    collisions: list[str]


@router.get("/catalog", response_model=list[CatalogCourseOut])
def get_catalog(
    tenant_id: UUID | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    target_tenant = _catalog_tenant(profile, tenant_id, required=False)
    return catalog_tree(get_service_client(), target_tenant)


@router.post("/catalog/provision", response_model=CatalogProvisionResult)
def provision_catalog_offerings(
    body: CatalogProvisionRequest,
    tenant_id: UUID | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> CatalogProvisionResult:
    target_tenant = _catalog_tenant(profile, tenant_id, required=True)
    assert target_tenant is not None
    subject_ids = list(
        dict.fromkeys(str(subject_id) for subject_id in body.catalog_subject_ids)
    )
    service = get_service_client()
    valid_ids = active_catalog_subject_ids(service, subject_ids)
    if valid_ids != set(subject_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more catalogue subjects are unavailable.",
        )

    collisions: list[str] = []
    for subject_id in subject_ids:
        result = provision_catalog_subject(
            service,
            tenant_id=target_tenant,
            catalog_subject_id=subject_id,
        )
        if result.course_name_collision or result.subject_name_collision:
            collisions.append(subject_id)
    return CatalogProvisionResult(
        provisioned=len(subject_ids),
        collisions=collisions,
    )


def _subjects_for(service, course_id: str, tenant_id: str) -> list[dict]:
    return (
        service.table("subjects")
        .select("id, name, course_level_id")
        .eq("course_id", course_id)
        .eq("tenant_id", tenant_id)
        .order("name")
        .execute()
        .data
        or []
    )


def _course_named(service, tenant_id: str, name: str) -> list[dict]:
    return (
        service.table("courses")
        .select("id, name")
        .eq("tenant_id", tenant_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )


def _subject_named(
    service, tenant_id: str, course_id: str, name: str
) -> list[dict]:
    return (
        service.table("subjects")
        .select("id, name, course_id")
        .eq("tenant_id", tenant_id)
        .eq("course_id", course_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )


def _chapter_named(
    service, tenant_id: str, subject_id: str, name: str
) -> list[dict]:
    return (
        service.table("chapters")
        .select("id, name, order_index")
        .eq("subject_id", subject_id)
        .eq("tenant_id", tenant_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )


@router.get("/public/courses")
def public_courses(tenant_id: UUID) -> list[dict]:
    """Active tenant courses and levels used by the self-signup form.

    Course names and IDs are intentionally public registration metadata; no
    student, staff, assessment, or analytics data is exposed here.

    Only courses belonging to an active institution are returned. This keeps
    the public signup choices aligned with the database signup trigger, which
    rejects courses belonging to inactive institutions.
    """
    service = get_service_client()
    rows = (
        service.table("courses")
        .select("id, name, tenants!inner(is_active)")
        .eq("tenant_id", str(tenant_id))
        .eq("tenants.is_active", True)
        .order("name")
        .execute()
        .data
        or []
    )
    course_ids = [str(row["id"]) for row in rows]
    levels = select_all_in(
        service,
        "course_levels",
        "id, course_id, name",
        in_column="course_id",
        values=course_ids,
        configure=lambda query: query.eq("tenant_id", str(tenant_id)).eq(
            "is_active", True
        ),
        order_column="name",
    )
    levels_by_course: dict[str, list[dict]] = {}
    for level in levels:
        levels_by_course.setdefault(str(level["course_id"]), []).append(
            {"id": str(level["id"]), "name": level["name"]}
        )
    return [
        {
            "id": str(row["id"]),
            "name": row["name"],
            "levels": levels_by_course.get(str(row["id"]), []),
        }
        for row in rows
        if levels_by_course.get(str(row["id"]))
    ]


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
    assigned = (
        teacher_subject_ids(service, profile)
        if profile.role == "teacher"
        else None
    )
    course_ids = [str(course["id"]) for course in courses]
    level_rows = select_all_in(
        service,
        "course_levels",
        "id, course_id, name, catalog_level_id",
        in_column="course_id",
        values=course_ids,
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
        order_column="name",
    )
    levels_by_course: dict[str, list[dict]] = {}
    for level in level_rows:
        levels_by_course.setdefault(str(level["course_id"]), []).append(
            {
                "id": str(level["id"]),
                "name": level["name"],
                "catalog_level_id": (
                    str(level["catalog_level_id"])
                    if level.get("catalog_level_id")
                    else None
                ),
            }
        )
    subjects_by_course: dict[str, list[dict]] = {}
    if course_ids:
        subjects_query = (
            service.table("subjects")
            .select("id, name, course_id, course_level_id, catalog_subject_id")
            .eq("tenant_id", profile.tenant_id)
            .in_("course_id", course_ids)
        )
        if assigned is not None:
            if not assigned:
                return []
            subjects_query = subjects_query.in_("id", sorted(assigned))
        subject_rows = subjects_query.order("name").execute().data or []
        level_by_id = {str(row["id"]): row for row in level_rows}
        for subject in subject_rows:
            level_id = str(subject.get("course_level_id") or "")
            level = level_by_id.get(level_id, {})
            subject_payload = {
                "id": subject["id"],
                "name": subject["name"],
                "course_level_id": level_id or None,
                "level_name": level.get("name"),
            }
            if subject.get("catalog_subject_id"):
                subject_payload["catalog_subject_id"] = str(
                    subject["catalog_subject_id"]
                )
            if level.get("catalog_level_id"):
                subject_payload["catalog_level_id"] = str(level["catalog_level_id"])
            subjects_by_course.setdefault(str(subject["course_id"]), []).append(
                subject_payload
            )

    student_count_by_course: dict[str, int] = {}
    if profile.role == "institution_admin" and courses:
        enrollments = (
            service.table("enrollments")
            .select("profile_id, course_id")
            .eq("tenant_id", profile.tenant_id)
            .in_("course_id", course_ids)
            .execute()
            .data
            or []
        )
        enrolled_ids = list({str(row["profile_id"]) for row in enrollments})
        student_ids: set[str] = set()
        if enrolled_ids:
            student_rows = (
                service.table("profiles")
                .select("id")
                .eq("tenant_id", profile.tenant_id)
                .eq("role", "student")
                .in_("id", enrolled_ids)
                .execute()
                .data
                or []
            )
            student_ids = {str(row["id"]) for row in student_rows}
        students_by_course: dict[str, set[str]] = {}
        for enrollment in enrollments:
            profile_id = str(enrollment["profile_id"])
            if profile_id in student_ids:
                students_by_course.setdefault(str(enrollment["course_id"]), set()).add(
                    profile_id
                )
        student_count_by_course = {
            course_id: len(profile_ids)
            for course_id, profile_ids in students_by_course.items()
        }
    visible_courses: list[dict] = []
    for course in courses:
        subjects = subjects_by_course.get(str(course["id"]), [])
        if assigned is not None and not subjects:
            continue
        course["subjects"] = subjects
        course["levels"] = levels_by_course.get(str(course["id"]), [])
        if profile.role == "institution_admin":
            course["student_count"] = student_count_by_course.get(str(course["id"]), 0)
        visible_courses.append(course)
    return visible_courses


class CourseCreate(BaseModel):
    name: str


class SubjectCreate(BaseModel):
    course_id: str
    course_level_id: str
    name: str


class CourseLevelCreate(BaseModel):
    course_id: str
    name: str


@router.post("/course-levels")
def create_course_level(
    body: CourseLevelCreate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_institution_admin(profile, action="manage courses and subjects")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Level name is required.")
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
    existing = (
        service.table("course_levels")
        .select("id, name")
        .eq("tenant_id", profile.tenant_id)
        .eq("course_id", body.course_id)
        .ilike("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return existing[0]
    inserted = (
        service.table("course_levels")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "course_id": body.course_id,
                "name": name,
            }
        )
        .execute()
        .data[0]
    )
    return {"id": inserted["id"], "name": inserted["name"]}


@router.post("/courses")
def create_course(
    body: CourseCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile, action="manage courses and subjects")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Course name is required.")
    service = get_service_client()
    # Reuse an existing course of the same name rather than duplicate it.
    existing = _course_named(service, profile.tenant_id, name)
    if existing:
        c = existing[0]
        return {**c, "subjects": _subjects_for(service, c["id"], profile.tenant_id)}
    try:
        inserted = (
            service.table("courses")
            .insert({"tenant_id": profile.tenant_id, "name": name})
            .execute()
            .data[0]
        )
        row = {"id": inserted["id"], "name": inserted["name"]}
    except Exception:  # noqa: BLE001 - recover a concurrent get-or-create race
        existing = _course_named(service, profile.tenant_id, name)
        if not existing:
            raise
        row = existing[0]
    return {**row, "subjects": []}


@router.post("/subjects")
def create_subject(
    body: SubjectCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile, action="manage courses and subjects")
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
    level = (
        service.table("course_levels")
        .select("id")
        .eq("id", body.course_level_id)
        .eq("course_id", body.course_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if level is None or not level.data:
        raise HTTPException(status_code=400, detail="Level does not belong to this course.")
    # Reuse an existing subject of the same name in this course.
    existing = _subject_named(service, profile.tenant_id, body.course_id, name)
    if existing:
        return {"id": existing[0]["id"], "name": existing[0]["name"]}
    try:
        inserted = (
            service.table("subjects")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "course_id": body.course_id,
                    "course_level_id": body.course_level_id,
                    "name": name,
                }
            )
            .execute()
            .data[0]
        )
        return {
            "id": inserted["id"],
            "name": inserted["name"],
            "course_level_id": body.course_level_id,
        }
    except Exception:  # noqa: BLE001 - recover a concurrent get-or-create race
        existing = _subject_named(service, profile.tenant_id, body.course_id, name)
        if not existing:
            raise
        return {"id": existing[0]["id"], "name": existing[0]["name"]}


@router.delete("/courses/{course_id}")
def delete_course(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile, action="manage courses and subjects")
    service = get_service_client()
    try:
        deleted = service.table("courses").delete().eq("id", course_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            409,
            "This course could not be deleted because it is still in use.",
            operation="delete course",
            exception=exc,
        ) from exc
    if not deleted.data:
        raise HTTPException(status_code=404, detail="Course not found.")
    return {"deleted": course_id}


@router.delete("/subjects/{subject_id}")
def delete_subject(
    subject_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_institution_admin(profile, action="manage courses and subjects")
    service = get_service_client()
    try:
        deleted = service.table("subjects").delete().eq("id", subject_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            409,
            "This subject could not be deleted because it is still in use.",
            operation="delete subject",
            exception=exc,
        ) from exc
    if not deleted.data:
        raise HTTPException(status_code=404, detail="Subject not found.")
    return {"deleted": subject_id}


# ── Teacher ⇄ subject assignment (institution-admin managed) ─────────────────
class TeacherSubjectsUpdate(BaseModel):
    subject_ids: list[UUID] = Field(default_factory=list, max_length=500)


class TeacherSubjectsResponse(BaseModel):
    subject_ids: list[str]


def _assert_tenant_teacher(service, teacher_id: str, profile: CurrentProfile) -> None:
    teacher = (
        service.table("profiles")
        .select("id, role")
        .eq("id", teacher_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if teacher is None or not teacher.data or teacher.data["role"] != "teacher":
        raise HTTPException(status_code=404, detail="Teacher not found.")


@router.get(
    "/teachers/{teacher_id}/subjects",
    response_model=TeacherSubjectsResponse,
)
def get_teacher_subjects(
    teacher_id: UUID,
    profile: CurrentProfile = Depends(get_current_profile),
) -> TeacherSubjectsResponse:
    require_institution_admin(profile, action="manage courses and subjects")
    service = get_service_client()
    teacher_id_str = str(teacher_id)
    _assert_tenant_teacher(service, teacher_id_str, profile)
    assigned = (
        service.table("teacher_subjects")
        .select("subject_id")
        .eq("teacher_id", teacher_id_str)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    return TeacherSubjectsResponse(
        subject_ids=[str(row["subject_id"]) for row in assigned]
    )


@router.put(
    "/teachers/{teacher_id}/subjects",
    response_model=TeacherSubjectsResponse,
)
def set_teacher_subjects(
    teacher_id: UUID,
    body: TeacherSubjectsUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> TeacherSubjectsResponse:
    """Replace a teacher's assignments in one database transaction."""
    require_institution_admin(profile, action="manage courses and subjects")
    service = get_service_client()
    teacher_id_str = str(teacher_id)
    subject_ids = list(
        dict.fromkeys(str(subject_id) for subject_id in body.subject_ids)
    )
    _assert_tenant_teacher(service, teacher_id_str, profile)

    if subject_ids:
        rows = (
            service.table("subjects")
            .select("id")
            .in_("id", subject_ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        )
        if {str(row["id"]) for row in rows} != set(subject_ids):
            raise HTTPException(
                status_code=400,
                detail="One or more subjects do not belong to this institution.",
            )

    try:
        assigned = replace_teacher_subjects(
            service,
            tenant_id=profile.tenant_id,
            teacher_id=teacher_id_str,
            subject_ids=subject_ids,
        )
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Could not update teacher subjects.",
        )
    return TeacherSubjectsResponse(subject_ids=assigned)


# ── Chapters (teacher-managed, within the teacher's own subjects) ─────────────
def _assert_teacher_subject(service, subject_id: str, profile: CurrentProfile) -> None:
    if subject_id not in teacher_subject_ids(service, profile):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage chapters in your own subjects.",
        )


@router.get("/subjects/{subject_id}/chapters")
def list_chapters(
    subject_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Chapters in a subject, with how many quizzes/questions use each (for the
    teacher's management view and the Generate-Quiz dropdown)."""
    require_teacher(profile, action="manage chapters")
    service = get_service_client()
    _assert_teacher_subject(service, subject_id, profile)

    return rpc_json_value(
        service,
        "teacher_chapter_metrics",
        {
            "p_tenant": profile.tenant_id,
            "p_teacher": profile.user_id,
            "p_subject": subject_id,
        },
        list,
    )


@router.get("/teacher/subject-metrics")
def teacher_subject_metrics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Per-subject teaching metrics for the teacher's Subjects dashboard.

    Returns, for each assigned subject: chapter count, quizzes (total /
    published / draft), question count, questions still pending review, student
    attempts, distinct students, and the overall average score (%) across graded
    attempts. Read-only and additive — the generation/extraction pipeline is
    untouched. Every query is tenant-scoped because the service client bypasses
    RLS, and the numbers are gathered in bulk (no per-subject round trips).
    """
    require_teacher(profile, action="manage chapters")
    return rpc_json_value(
        get_service_client(),
        "teacher_subject_metrics",
        {"p_tenant": profile.tenant_id, "p_teacher": profile.user_id},
        list,
    )


class ChapterCreate(BaseModel):
    subject_id: str
    name: str


@router.post("/chapters")
def create_chapter(
    body: ChapterCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_teacher(profile, action="manage chapters")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Chapter name is required.")
    service = get_service_client()
    _assert_teacher_subject(service, body.subject_id, profile)

    # Reuse an existing chapter with the same name rather than duplicate it.
    existing = _chapter_named(service, profile.tenant_id, body.subject_id, name)
    if existing:
        return {**existing[0], "quiz_count": 0, "question_count": 0}

    last = (
        service.table("chapters")
        .select("order_index")
        .eq("subject_id", body.subject_id)
        .eq("tenant_id", profile.tenant_id)
        .order("order_index", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    next_idx = (last[0]["order_index"] + 1) if last else 0
    try:
        inserted = (
            service.table("chapters")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "subject_id": body.subject_id,
                    "name": name,
                    "order_index": next_idx,
                }
            )
            .execute()
            .data[0]
        )
        row = {
            "id": inserted["id"],
            "name": inserted["name"],
            "order_index": inserted["order_index"],
        }
    except Exception:  # noqa: BLE001 - recover a concurrent get-or-create race
        existing = _chapter_named(service, profile.tenant_id, body.subject_id, name)
        if not existing:
            raise
        row = existing[0]
    return {**row, "quiz_count": 0, "question_count": 0}


@router.delete("/chapters/{chapter_id}")
def delete_chapter(
    chapter_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    require_teacher(profile, action="manage chapters")
    service = get_service_client()
    chap = (
        service.table("chapters")
        .select("id, subject_id")
        .eq("id", chapter_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if chap is None or not chap.data:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    _assert_teacher_subject(service, chap.data["subject_id"], profile)

    # Protect existing content: refuse to delete a chapter that's still in use.
    quiz_n = len(
        service.table("quiz_sets")
        .select("id")
        .eq("chapter_id", chapter_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    ques_n = len(
        service.table("questions")
        .select("id")
        .eq("chapter_id", chapter_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    if quiz_n or ques_n:
        bits = []
        if quiz_n:
            bits.append(f"{quiz_n} quiz{'zes' if quiz_n != 1 else ''}")
        if ques_n:
            bits.append(f"{ques_n} question{'s' if ques_n != 1 else ''}")
        raise HTTPException(
            status_code=409,
            detail=f"This chapter is used by {' and '.join(bits)}. "
            "Move or delete those first.",
        )
    service.table("chapters").delete().eq("id", chapter_id).eq(
        "tenant_id", profile.tenant_id
    ).execute()
    return {"deleted": chapter_id}
