"""Authoritative tenant, entitlement and academic access checks for evaluation."""
from __future__ import annotations

from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.lib.supabase_queries import select_all_in
from app.services.teacher_access import teacher_has_subject, teacher_subject_ids


def require_evaluation_enabled(service, profile: CurrentProfile) -> None:
    row = (
        service.table("tenants").select("handwritten_evaluation_enabled")
        .eq("id", profile.tenant_id).maybe_single().execute()
    )
    if row is None or not row.data or not row.data.get("handwritten_evaluation_enabled"):
        raise HTTPException(403, "Handwritten evaluation is not enabled for this institution.")


def require_teacher_paper_scope(
    service, profile: CurrentProfile, *, course_level_id: str, subject_id: str
) -> None:
    assignment = (
        service.table("teacher_subjects").select("subject_id")
        .eq("tenant_id", profile.tenant_id).eq("teacher_id", profile.user_id)
        .eq("subject_id", subject_id).maybe_single().execute()
    )
    subject = (
        service.table("subjects").select("id")
        .eq("tenant_id", profile.tenant_id).eq("id", subject_id)
        .eq("course_level_id", course_level_id).maybe_single().execute()
    )
    if not assignment or not assignment.data or not subject or not subject.data:
        raise HTTPException(404, "Assigned subject and course level not found.")


def assigned_evaluation_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Return the authoritative subject scope for an evaluation teacher."""
    if profile.role != "teacher":
        return set()
    return teacher_subject_ids(service, profile)


def require_teacher_evaluation_paper_access(
    service, profile: CurrentProfile, *, paper_id: str
) -> None:
    """Hide an evaluation paper unless it belongs to an assigned subject."""
    paper = (
        service.table("evaluation_papers")
        .select("subject_id")
        .eq("id", paper_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if (
        paper is None
        or not paper.data
        or not teacher_has_subject(service, profile, str(paper.data["subject_id"]))
    ):
        raise HTTPException(404, "Evaluation paper not found.")


def teacher_can_inspect_student_learning(
    service,
    profile: CurrentProfile,
    *,
    student_id: str,
    subject_ids: set[str],
) -> bool:
    """Check that a student has evaluation work in the teacher's subject scope."""
    if profile.role != "teacher" or not subject_ids:
        return False
    papers = select_all_in(
        service,
        "evaluation_papers",
        "id",
        in_column="subject_id",
        values=sorted(subject_ids),
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
    )
    paper_ids = [str(row["id"]) for row in papers]
    if not paper_ids:
        return False
    submissions = select_all_in(
        service,
        "handwritten_submissions",
        "id",
        in_column="evaluation_paper_id",
        values=paper_ids,
        configure=lambda query: query.eq("tenant_id", profile.tenant_id).eq(
            "student_id", student_id
        ),
    )
    return bool(submissions)


def student_can_access_paper(service, profile: CurrentProfile, paper: dict) -> bool:
    subject = (
        service.table("subjects").select("course_id,course_level_id")
        .eq("id", paper["subject_id"]).eq("tenant_id", profile.tenant_id)
        .eq("course_level_id", paper["course_level_id"]).maybe_single().execute()
    )
    if not subject or not subject.data:
        return False
    enrollment = (
        service.table("enrollments").select("id")
        .eq("tenant_id", profile.tenant_id).eq("profile_id", profile.user_id)
        .eq("course_id", subject.data["course_id"])
        .eq("course_level_id", paper["course_level_id"]).maybe_single().execute()
    )
    return bool(enrollment and enrollment.data)
