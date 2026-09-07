"""Authoritative teacher-to-subject access helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.lib.auth import CurrentProfile


def teacher_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Return the subjects explicitly assigned to this teacher."""
    rows = (
        service.table("teacher_subjects")
        .select("subject_id")
        .eq("teacher_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    return {str(row["subject_id"]) for row in rows}


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
