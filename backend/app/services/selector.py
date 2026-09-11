"""
Question selector — chooses which questions a self-serve practice session runs
over (Smart Quiz, chapter practice, exam simulator, daily challenge, …).

Hard rule (multi-tenant safety): selection is ALWAYS scoped to
  * the student's own tenant,
  * subjects of the courses the student is enrolled in,
  * and review_status = 'approved' (never unreviewed/draft questions).
There is no cross-tenant selection — a student only ever sees their own
institution's approved questions.
"""

from __future__ import annotations

import random

from app.lib.auth import CurrentProfile

# Absolute ceiling on how many questions one selection scans / returns.
# 100 covers a full-length exam (e.g. CA Foundation 100Q); shorter modes cap lower.
_MAX_POOL = 2000
_MAX_COUNT = 100
SELECTABLE_QUESTION_TYPES = (
    "mcq_single",
    "mcq_multi",
    "true_false",
    "numerical",
    "fill_blank",
)


def enrolled_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Subjects of the courses this student is enrolled in."""
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


def _chapter_ids(service, subject_ids: list[str], tenant_id: str) -> list[str]:
    if not subject_ids:
        return []
    rows = (
        service.table("chapters")
        .select("id")
        .in_("subject_id", subject_ids)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    return [r["id"] for r in rows]


def select_question_ids(
    service,
    profile: CurrentProfile,
    *,
    mode: str = "smart",
    subject_id: str | None = None,
    chapter_id: str | None = None,
    count: int = 15,
    difficulty: str | None = None,
) -> list[str]:
    """Return up to `count` random approved question ids for this student.

    Scope: chapter (if given) -> subject (if given) -> all enrolled subjects.
    Returns [] if the student isn't allowed the target or nothing matches.
    """
    tenant_id = profile.tenant_id
    count = max(1, min(count, _MAX_COUNT))
    allowed = enrolled_subject_ids(service, profile)
    if not allowed:
        return []

    # Resolve the chapter scope, enforcing enrolment the whole way down.
    if chapter_id:
        chap = (
            service.table("chapters")
            .select("subject_id")
            .eq("id", chapter_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if chap is None or not chap.data or chap.data["subject_id"] not in allowed:
            return []
        chapter_ids = [chapter_id]
    elif subject_id:
        if subject_id not in allowed:
            return []
        chapter_ids = _chapter_ids(service, [subject_id], tenant_id)
    else:
        chapter_ids = _chapter_ids(service, list(allowed), tenant_id)

    if not chapter_ids:
        return []

    q = (
        service.table("questions")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("review_status", "approved")
        .in_("chapter_id", chapter_ids)
    )
    if difficulty:
        q = q.eq("difficulty", difficulty)

    rows = q.limit(_MAX_POOL).execute().data or []
    ids = [r["id"] for r in rows]
    random.shuffle(ids)
    return ids[:count]


def select_question_ids_by_type(
    service,
    profile: CurrentProfile,
    *,
    subject_id: str | None,
    type_counts: dict[str, int],
) -> tuple[list[str], dict[str, int]]:
    """Select an exact randomized mix without silently substituting types."""
    tenant_id = profile.tenant_id
    allowed = enrolled_subject_ids(service, profile)
    if not allowed or (subject_id and subject_id not in allowed):
        return [], {question_type: 0 for question_type in type_counts}

    chapter_ids = _chapter_ids(
        service, [subject_id] if subject_id else list(allowed), tenant_id
    )
    if not chapter_ids:
        return [], {question_type: 0 for question_type in type_counts}

    requested_types = [
        question_type for question_type, count in type_counts.items() if count > 0
    ]
    if not requested_types:
        return [], {}
    rows = (
        service.table("questions")
        .select("id, type")
        .eq("tenant_id", tenant_id)
        .eq("review_status", "approved")
        .in_("chapter_id", chapter_ids)
        .in_("type", requested_types)
        .limit(_MAX_POOL)
        .execute()
        .data
        or []
    )
    pools = {question_type: [] for question_type in requested_types}
    for row in rows:
        question_type = row.get("type")
        if question_type in pools:
            pools[question_type].append(row["id"])

    selected: list[str] = []
    availability: dict[str, int] = {}
    for question_type in requested_types:
        pool = pools[question_type]
        random.shuffle(pool)
        availability[question_type] = len(pool)
        selected.extend(pool[: type_counts[question_type]])
    random.shuffle(selected)
    return selected, availability
