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


# ── Chapters (teacher-managed, within the teacher's own subjects) ─────────────
def _require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can manage chapters.",
        )


def _teacher_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Subjects that belong to the courses this teacher is mapped to."""
    enrolled = (
        service.table("enrollments")
        .select("course_id")
        .eq("profile_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    course_ids = [e["course_id"] for e in enrolled]
    if not course_ids:
        return set()
    subs = (
        service.table("subjects")
        .select("id")
        .in_("course_id", course_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    return {s["id"] for s in subs}


def _assert_teacher_subject(service, subject_id: str, profile: CurrentProfile) -> None:
    if subject_id not in _teacher_subject_ids(service, profile):
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
    existing = (
        service.table("chapters")
        .select("id, name, order_index")
        .eq("subject_id", body.subject_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return {**existing[0], "quiz_count": 0, "question_count": 0}

    last = (
        service.table("chapters")
        .select("order_index")
        .eq("subject_id", body.subject_id)
        .order("order_index", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    next_idx = (last[0]["order_index"] + 1) if last else 0
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
