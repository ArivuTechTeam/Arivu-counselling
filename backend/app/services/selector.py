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
from app.lib.config import get_settings
from app.lib.supabase_queries import rpc_json_value, select_all_in
from app.services.tenant_features import profile_feature_enabled

# 100 covers a full-length exam (e.g. CA Foundation 100Q); shorter modes cap lower.
_MAX_COUNT = 100
_MAX_SAMPLE_KEY = 9223372036854775807
SELECTABLE_QUESTION_TYPES = (
    "mcq_single",
    "mcq_multi",
    "true_false",
    "numerical",
    "fill_blank",
)


def enrolled_subject_ids(service, profile: CurrentProfile) -> set[str]:
    """Subjects in the student's enrolled course and operational level.

    A NULL level is retained only for legacy rows and teacher compatibility; it
    keeps the previous course-wide behavior until that enrollment is corrected.
    """
    enrolled = (
        service.table("enrollments")
        .select("course_id, course_level_id")
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
        .select("id, course_id, course_level_id")
        .in_("course_id", course_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    levels_by_course = {
        str(enrollment["course_id"]): (
            str(enrollment["course_level_id"])
            if enrollment.get("course_level_id")
            else None
        )
        for enrollment in enrolled
    }
    return {
        str(subject["id"])
        for subject in subs
        if levels_by_course.get(str(subject["course_id"])) is None
        or str(subject.get("course_level_id"))
        == levels_by_course[str(subject["course_id"])]
    }


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


def _accessible_published_set_ids(service, published_rows, tenant_id, profile) -> set[str]:
    """Of these PUBLISHED quiz sets, the ones the student may practice from.

    Legacy-course quizzes: all (unchanged). Assigned-batch quizzes: only those the
    student can reach via an available batch assignment — so one batch's exam
    items never leak into another batch's practice pool. With BATCHES_ENABLED off
    (or no profile) this is every published set, i.e. the current behavior.
    """
    batches_enabled = _batches_enabled(profile)
    if not batches_enabled:
        return {row["id"] for row in published_rows}
    from app.services.batch_access import assigned_quiz_ids

    accessible_assigned = assigned_quiz_ids(
        service, tenant_id=tenant_id, profile_id=profile.user_id
    )
    return {
        row["id"]
        for row in published_rows
        if (row.get("audience_mode") or "legacy_course") == "legacy_course"
        or row["id"] in accessible_assigned
    }


def _batches_enabled(profile: CurrentProfile | None) -> bool:
    return bool(
        profile
        and (
            getattr(get_settings(), "batches_enabled", False)
            if getattr(profile, "tenant_feature_flags", None) is None
            else profile_feature_enabled(profile, "batches")
        )
    )


def _sample_practice_question_ids(
    service,
    profile: CurrentProfile,
    *,
    count: int,
    subject_id: str | None,
    chapter_id: str | None,
    difficulty: str | None,
    question_type: str | None,
) -> tuple[list[str], int]:
    """Run one indexed random-key seek and validate its compact RPC result."""
    requested = max(1, min(int(count), _MAX_COUNT))
    payload = rpc_json_value(
        service,
        "select_practice_question_ids_page",
        {
            "p_tenant": profile.tenant_id,
            "p_student": profile.user_id,
            "p_limit": requested,
            "p_start_key": random.randrange(_MAX_SAMPLE_KEY + 1),
            "p_batches_enabled": _batches_enabled(profile),
            "p_subject": subject_id,
            "p_chapter": chapter_id,
            "p_difficulty": difficulty,
            "p_question_type": question_type,
        },
        dict,
    )
    raw_ids = payload.get("question_ids")
    available = payload.get("available")
    if (
        not isinstance(raw_ids, list)
        or any(not isinstance(question_id, str) for question_id in raw_ids)
        or isinstance(available, bool)
        or not isinstance(available, int)
    ):
        raise RuntimeError(
            "select_practice_question_ids_page returned an invalid payload"
        )
    ids = list(dict.fromkeys(raw_ids))
    if len(ids) != len(raw_ids) or len(ids) > requested or available != len(ids):
        raise RuntimeError(
            "select_practice_question_ids_page returned an invalid selection"
        )
    return ids, available


def _released_practice_ids(
    service, question_ids: list[str], tenant_id: str, *, profile: CurrentProfile | None = None
) -> set[str]:
    """Linked draft/archive content must not leak through self-serve practice.

    Existing standalone approved bank items remain available. A quiz-linked item
    is available only through a quiz the student may access — a currently
    published quiz, and (when batches are enabled) an assigned-batch quiz only for
    that batch's members.
    """
    links = select_all_in(
        service, "quiz_variant_questions", "id,question_id,variant_id",
        in_column="question_id", values=question_ids,
        configure=lambda q: q.eq("tenant_id", tenant_id),
    )
    linked_ids = {row["question_id"] for row in links}
    if not links:
        return set(question_ids)
    variants = select_all_in(
        service, "quiz_variants", "id,quiz_set_id",
        in_column="id", values=[row["variant_id"] for row in links],
        configure=lambda q: q.eq("tenant_id", tenant_id),
    )
    published = select_all_in(
        service, "quiz_sets", "id, audience_mode", in_column="id",
        values=[row["quiz_set_id"] for row in variants],
        configure=lambda q: q.eq("tenant_id", tenant_id).eq("status", "published"),
    )
    accessible_set_ids = _accessible_published_set_ids(service, published, tenant_id, profile)
    released_variants = {row["id"] for row in variants if row["quiz_set_id"] in accessible_set_ids}
    return (set(question_ids) - linked_ids) | {
        row["question_id"] for row in links if row["variant_id"] in released_variants
    }


def accessible_practice_question_ids(
    service, question_ids: list[str], tenant_id: str, profile: CurrentProfile
) -> set[str]:
    """Public wrapper: the subset of `question_ids` this student may access via
    practice rules (used to gate taking a shared challenge)."""
    return _released_practice_ids(service, question_ids, tenant_id, profile=profile)


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
    count = max(1, min(count, _MAX_COUNT))
    ids, _available = _sample_practice_question_ids(
        service,
        profile,
        count=count,
        subject_id=subject_id,
        chapter_id=chapter_id,
        difficulty=difficulty,
        question_type=None,
    )
    return ids


def select_question_ids_by_type(
    service,
    profile: CurrentProfile,
    *,
    subject_id: str | None,
    type_counts: dict[str, int],
) -> tuple[list[str], dict[str, int]]:
    """Select an exact randomized mix without silently substituting types."""
    requested_types = [
        question_type for question_type, count in type_counts.items() if count > 0
    ]
    if not requested_types:
        return [], {}

    selected: list[str] = []
    availability: dict[str, int] = {}
    remaining = _MAX_COUNT
    for question_type in requested_types:
        requested = min(max(int(type_counts[question_type]), 0), remaining)
        if requested == 0:
            availability[question_type] = 0
            continue
        ids, available = _sample_practice_question_ids(
            service,
            profile,
            count=requested,
            subject_id=subject_id,
            chapter_id=None,
            difficulty=None,
            question_type=question_type,
        )
        availability[question_type] = available
        selected.extend(ids)
        remaining -= requested
    random.shuffle(selected)
    return selected, availability
