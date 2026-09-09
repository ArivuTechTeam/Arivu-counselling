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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.supabase import get_service_client
from app.services.teacher_access import (
    replace_teacher_subjects,
    teacher_subject_ids,
)

router = APIRouter(prefix="/api/v1", tags=["academics"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _require_admin(profile: CurrentProfile) -> None:
    if profile.role != "institution_admin":
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
    assigned = (
        teacher_subject_ids(service, profile)
        if profile.role == "teacher"
        else None
    )
    student_count_by_course: dict[str, int] = {}
    if profile.role == "institution_admin" and courses:
        course_ids = [str(course["id"]) for course in courses]
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
        subjects = _subjects_for(service, course["id"], profile.tenant_id)
        if assigned is not None:
            subjects = [subject for subject in subjects if subject["id"] in assigned]
            if not subjects:
                continue
        course["subjects"] = subjects
        if profile.role == "institution_admin":
            course["student_count"] = student_count_by_course.get(str(course["id"]), 0)
        visible_courses.append(course)
    return visible_courses


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
    # Reuse an existing course of the same name rather than duplicate it.
    existing = _course_named(service, profile.tenant_id, name)
    if existing:
        c = existing[0]
        return {**c, "subjects": _subjects_for(service, c["id"], profile.tenant_id)}
    try:
        row = (
            service.table("courses")
            .insert({"tenant_id": profile.tenant_id, "name": name})
            .execute()
            .data[0]
        )
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
    # Reuse an existing subject of the same name in this course.
    existing = _subject_named(service, profile.tenant_id, body.course_id, name)
    if existing:
        return existing[0]
    try:
        return (
            service.table("subjects")
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
    except Exception:  # noqa: BLE001 - recover a concurrent get-or-create race
        existing = _subject_named(service, profile.tenant_id, body.course_id, name)
        if not existing:
            raise
        return existing[0]


@router.delete("/courses/{course_id}")
def delete_course(
    course_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_admin(profile)
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
    _require_admin(profile)
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
    _require_admin(profile)
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
    _require_admin(profile)
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
def _require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can manage chapters.",
        )


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
    _require_teacher(profile)
    service = get_service_client()
    _assert_teacher_subject(service, subject_id, profile)

    chapters = (
        service.table("chapters")
        .select("id, name, order_index")
        .eq("subject_id", subject_id)
        .eq("tenant_id", profile.tenant_id)
        .order("order_index")
        .order("name")
        .execute()
        .data
        or []
    )
    ids = [c["id"] for c in chapters]
    quiz_counts: dict = {}
    q_counts: dict = {}
    if ids:
        for r in (
            service.table("quiz_sets")
            .select("chapter_id")
            .in_("chapter_id", ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        ):
            quiz_counts[r["chapter_id"]] = quiz_counts.get(r["chapter_id"], 0) + 1
        for r in (
            service.table("questions")
            .select("chapter_id")
            .in_("chapter_id", ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        ):
            q_counts[r["chapter_id"]] = q_counts.get(r["chapter_id"], 0) + 1
    return [
        {
            **c,
            "quiz_count": quiz_counts.get(c["id"], 0),
            "question_count": q_counts.get(c["id"], 0),
        }
        for c in chapters
    ]


class ChapterCreate(BaseModel):
    subject_id: str
    name: str


@router.post("/chapters")
def create_chapter(
    body: ChapterCreate, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_teacher(profile)
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
        row = (
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
    _require_teacher(profile)
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
