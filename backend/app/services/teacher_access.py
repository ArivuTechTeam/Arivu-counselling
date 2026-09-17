"""Authoritative teacher-to-subject access helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.lib.auth import CurrentProfile
from app.lib.supabase_queries import select_all, select_all_in


def teacher_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Return the subjects explicitly assigned to this teacher."""
    rows = select_all(
        service,
        "teacher_subjects",
        "subject_id",
        configure=lambda query: query.eq("teacher_id", profile.user_id).eq(
            "tenant_id", profile.tenant_id
        ),
        order_column="subject_id",
    )
    return {str(row["subject_id"]) for row in rows}


def teacher_course_ids(service, profile: CurrentProfile) -> set[str]:
    """Return courses reached through the teacher's current subject assignments."""
    subject_ids = teacher_subject_ids(service, profile)
    if not subject_ids:
        return set()
    rows = select_all_in(
        service,
        "subjects",
        "id, course_id",
        in_column="id",
        values=sorted(subject_ids),
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
    )
    return {str(row["course_id"]) for row in rows if row.get("course_id")}


def teacher_student_ids(service, profile: CurrentProfile) -> set[str]:
    """Return student profiles in courses currently assigned to the teacher."""
    course_ids = teacher_course_ids(service, profile)
    if not course_ids:
        return set()
    enrollments = select_all_in(
        service,
        "enrollments",
        "id, profile_id",
        in_column="course_id",
        values=sorted(course_ids),
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
    )
    enrolled_ids = {str(row["profile_id"]) for row in enrollments}
    if not enrolled_ids:
        return set()
    students = select_all_in(
        service,
        "profiles",
        "id",
        in_column="id",
        values=sorted(enrolled_ids),
        configure=lambda query: query.eq("tenant_id", profile.tenant_id)
        .eq("role", "student"),
    )
    return {str(row["id"]) for row in students}


def teacher_has_subject(
    service, profile: CurrentProfile, subject_id: str
) -> bool:
    """Check a subject assignment without trusting course enrolment."""
    row = (
        service.table("teacher_subjects")
        .select("subject_id")
        .eq("teacher_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("subject_id", subject_id)
        .maybe_single()
        .execute()
    )
    return bool(row is not None and row.data)


def replace_teacher_subjects(
    service,
    *,
    tenant_id: str,
    teacher_id: str,
    subject_ids: Iterable[str],
) -> list[str]:
    """Atomically replace assignments and their derived course enrolments."""
    unique_ids = list(dict.fromkeys(str(subject_id) for subject_id in subject_ids))
    result = service.rpc(
        "replace_teacher_subjects",
        {
            "p_tenant_id": tenant_id,
            "p_teacher_id": teacher_id,
            "p_subject_ids": unique_ids,
        },
    ).execute()
    return [str(subject_id) for subject_id in (result.data or unique_ids)]
