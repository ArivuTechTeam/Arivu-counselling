"""
Events ledger — append-only instrumentation.

Every meaningful action in the app writes ONE row to the `events` table via this
module. That raw stream is what the super-admin product-intelligence dashboards
read (through database-side aggregation) to answer questions like
"how often is an AI question approved WITHOUT edits?".

Design rule — logging is BEST-EFFORT and MUST NEVER break the user action it
records. Every write is wrapped and swallows exceptions. If the `events` table
doesn't exist yet (migration 02 not run), or an insert fails, the app keeps
working exactly as before; we simply don't record that event.
"""

from __future__ import annotations

import logging
from typing import Any

from app.lib.supabase import get_service_client

log = logging.getLogger("events")

# --- Event vocabulary (keep these consistent across the codebase) ------------
QUESTION_GENERATED = "question.generated"
QUESTION_EDITED = "question.edited"
QUESTION_APPROVED = "question.approved"
QUESTION_REJECTED = "question.rejected"
QUESTION_REGENERATED = "question.regenerated"
QUESTION_UNREJECTED = "question.unrejected"
QUESTION_PURGED = "question.purged_rejected"
QUIZ_PUBLISHED = "quiz.published"
ATTEMPT_SUBMITTED = "attempt.submitted"
DOCUMENT_UPLOADED = "document.uploaded"
GENERATION_FAILED = "generation.failed"


def make_event(
    *,
    tenant_id: str,
    event_type: str,
    actor_id: str | None = None,
    actor_role: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape a single event row (for batch logging via log_events)."""
    return {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "metadata": metadata or {},
    }


def log_event(**kwargs: Any) -> None:
    """Append ONE event. Never raises. Accepts the same kwargs as make_event()."""
    _insert([make_event(**kwargs)])


def log_events(rows: list[dict[str, Any]]) -> None:
    """Append MANY events in a single insert. Never raises."""
    _insert(rows)


def _insert(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        get_service_client().table("events").insert(rows).execute()
    except Exception as exc:  # noqa: BLE001 — instrumentation must never break the app
        # Debug-level on purpose: a missing table or transient failure here is
        # not an application error; we just skip recording. Do not attach the
        # raw exception because SDK errors can include response bodies.
        log.debug(
            "event logging skipped (%d rows, %s)",
            len(rows),
            type(exc).__name__,
        )
