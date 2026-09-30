"""Authoritative tenant, entitlement and academic access checks for evaluation."""
from __future__ import annotations

from fastapi import HTTPException

from app.lib.auth import CurrentProfile


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
