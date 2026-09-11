"""Shared authorization checks for student access to question-level data."""

from __future__ import annotations

from app.lib.auth import CurrentProfile


def student_has_graded_question(
    service, question_id: str, profile: CurrentProfile
) -> bool:
    """Whether this student has submitted this question in either quiz engine."""
    attempt_answers = (
        service.table("attempt_answers")
        .select("attempt_id")
        .eq("question_id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    attempt_ids = [row["attempt_id"] for row in attempt_answers]
    if attempt_ids:
        attempts = (
            service.table("quiz_attempts")
            .select("id")
            .in_("id", attempt_ids)
            .eq("tenant_id", profile.tenant_id)
            .eq("student_id", profile.user_id)
            .eq("status", "graded")
            .limit(1)
            .execute()
            .data
            or []
        )
        if attempts:
            return True

    practice_answers = (
        service.table("practice_answers")
        .select("session_id")
        .eq("question_id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    session_ids = [row["session_id"] for row in practice_answers]
    if not session_ids:
        return False
    sessions = (
        service.table("practice_sessions")
        .select("id")
        .in_("id", session_ids)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("status", "graded")
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(sessions)
