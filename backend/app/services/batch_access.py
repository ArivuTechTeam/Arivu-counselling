"""Batch-scoped student access resolution (Phase 6.1).

Single source of truth for whether a STUDENT may see or attempt a quiz, honoring
``quiz_sets.audience_mode`` + batch assignments + membership + the optional
availability window, gated by ``BATCHES_ENABLED``.

Non-breaking rule:
- Flag OFF, or a quiz whose ``audience_mode = 'legacy_course'`` → the legacy
  course-wide rule applies (published + subject in the student's enrolled
  subjects). This is the current behavior, unchanged.
- Flag ON and ``audience_mode = 'assigned_batches'`` → visible only when an
  ACTIVE assignment (within its window) targets a batch the student is an ACTIVE
  member of.

Enforcement lives in the read paths (P6.1-3); this module only decides access.
Backend callers use the service-role client, so these reads bypass RLS by design.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.lib.config import get_settings
from app.lib.supabase_queries import select_all_in
from app.services.selector import enrolled_subject_ids

LEGACY_COURSE = "legacy_course"
ASSIGNED_BATCHES = "assigned_batches"


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---- pure predicates (unit-tested without a database) ----------------------

def assignment_available(assignment: dict, now: datetime) -> bool:
    """An assignment is available when it is active and ``now`` is inside its
    optional [available_from, available_to] window."""
    if (assignment.get("status") or "active") != "active":
        return False
    start = _parse_ts(assignment.get("available_from"))
    if start is not None and now < start:
        return False
    end = _parse_ts(assignment.get("available_to"))
    if end is not None and now > end:
        return False
    return True


def membership_active(membership: dict, today: date) -> bool:
    """A membership is active when its flag is set and ``today`` is inside its
    optional [valid_from, valid_to] range."""
    if not membership.get("active", True):
        return False
    valid_from = _parse_date(membership.get("valid_from"))
    if valid_from is not None and today < valid_from:
        return False
    valid_to = _parse_date(membership.get("valid_to"))
    if valid_to is not None and today > valid_to:
        return False
    return True


# ---- database-backed resolution --------------------------------------------

def active_batch_ids(
    service, *, tenant_id: str, profile_id: str, now: datetime | None = None
) -> set[str]:
    """The batch ids the profile is an ACTIVE member of (any role)."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    rows = (
        service.table("batch_memberships")
        .select("batch_id, active, valid_from, valid_to")
        .eq("tenant_id", tenant_id)
        .eq("profile_id", profile_id)
        .execute()
        .data
        or []
    )
    return {
        row["batch_id"]
        for row in rows
        if row.get("batch_id") and membership_active(row, today)
    }


def assigned_quiz_ids(
    service, *, tenant_id: str, profile_id: str, now: datetime | None = None
) -> set[str]:
    """Quiz-set ids reachable via an AVAILABLE assignment to an ACTIVE batch of
    the student. Does not itself check publish/audience state — callers pair this
    with the published `assigned_batches` set (list) or `student_can_access_quiz`.
    """
    now = now or datetime.now(timezone.utc)
    batch_ids = active_batch_ids(
        service, tenant_id=tenant_id, profile_id=profile_id, now=now
    )
    if not batch_ids:
        return set()
    rows = select_all_in(
        service,
        "quiz_assignments",
        "quiz_set_id, batch_id, status, available_from, available_to",
        in_column="batch_id",
        values=list(batch_ids),
        configure=lambda query: query.eq("tenant_id", tenant_id),
    )
    return {
        row["quiz_set_id"]
        for row in rows
        if row.get("quiz_set_id") and assignment_available(row, now)
    }


def student_can_access_quiz(
    service, profile, quiz_set_id: str, *, now: datetime | None = None
) -> bool:
    """Authoritative single-quiz gate for attempt-start and any direct-id load.

    A quiz must be published. Then, per audience mode + the flag, either the
    legacy course-subject rule or the batch-assignment rule decides access.
    """
    result = (
        service.table("quiz_sets")
        .select("id, status, subject_id, audience_mode")
        .eq("id", quiz_set_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    row = result.data if result and result.data else None
    if not row or row.get("status") != "published":
        return False

    audience = row.get("audience_mode") or LEGACY_COURSE
    if not getattr(get_settings(), "batches_enabled", False) or audience == LEGACY_COURSE:
        # Legacy course-wide rule (unchanged): published + subject enrolled.
        return row.get("subject_id") in enrolled_subject_ids(service, profile)

    # assigned_batches: reachable only via an available assignment to an active batch.
    return quiz_set_id in assigned_quiz_ids(
        service, tenant_id=profile.tenant_id, profile_id=profile.user_id, now=now
    )
