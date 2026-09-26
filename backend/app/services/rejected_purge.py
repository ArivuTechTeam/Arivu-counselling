"""
Purge rejected questions at publish time (feature-flagged).

When REJECTED_PURGE_ENABLED is on, publishing a quiz permanently deletes the
questions the teacher marked `rejected` for that quiz, so rejected content never
lingers in the `questions` table (and can never be pulled by Smart Quiz, which
already filters to review_status='approved'). When the flag is off, nothing here
runs and rejecting stays a pure soft-flag exactly as before.

Safety rules (a delete must never corrupt data):
  * Only questions with review_status='rejected' that belong to THIS quiz's
    variants and were created by the publishing teacher are considered.
  * A rejected question that was EVER answered by a student (attempt_answers or
    practice_answers) is NEVER deleted - it is kept soft-rejected so past
    results stay intact. In the normal "reject during first review, then
    publish" flow no student has answered yet, so this guard simply never fires.
  * Foreign keys without a cascade are cleared first (quiz_variant_questions);
    bookmarks and ai_explanations cascade automatically; quiz_attempts keep a
    frozen JSON snapshot so they are unaffected; paper_questions keeps only a
    non-FK lineage id so its snapshot survives.
  * Every deletion writes a best-effort `question.purged_rejected` audit event.

The function never raises for a purge problem: publishing has already succeeded
by the time it runs, and a failure to clean up must not fail the publish. It
returns how many questions were purged (and how many were kept for history).
"""

from __future__ import annotations

import logging

from app.services.events import QUESTION_PURGED, log_events, make_event

log = logging.getLogger("rejected_purge")

# Child tables that reference questions(id) WITHOUT an on-delete cascade and
# that record a student's answer. Presence of any row here means the question
# was answered, so it must be preserved (never hard-deleted).
_ANSWER_TABLES = ("attempt_answers", "practice_answers")


def _was_ever_answered(service, question_id: str) -> bool:
    """True if a student ever answered this question. Conservative: if we cannot
    verify (query error / unknown table), assume answered so we never delete
    history we could not check."""
    for table in _ANSWER_TABLES:
        try:
            rows = (
                service.table(table)
                .select("question_id")
                .eq("question_id", question_id)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception:  # noqa: BLE001 - cannot verify -> keep the question
            return True
        if rows:
            return True
    return False


def _rejected_question_ids(service, tenant_id: str, created_by: str, quiz_set_id: str) -> list[str]:
    """The rejected question ids linked to this quiz set's variants."""
    variants = (
        service.table("quiz_variants")
        .select("id")
        .eq("quiz_set_id", quiz_set_id)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    variant_ids = [str(v["id"]) for v in variants]
    if not variant_ids:
        return []
    links = (
        service.table("quiz_variant_questions")
        .select("question_id")
        .in_("variant_id", variant_ids)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    question_ids = list({str(link["question_id"]) for link in links})
    if not question_ids:
        return []
    rejected = (
        service.table("questions")
        .select("id")
        .in_("id", question_ids)
        .eq("tenant_id", tenant_id)
        .eq("created_by", created_by)
        .eq("review_status", "rejected")
        .execute()
        .data
        or []
    )
    return [str(row["id"]) for row in rejected]


def _delete_question(service, tenant_id: str, question_id: str) -> None:
    """Remove the non-cascading link rows, then the question itself. Guarded on
    review_status so a concurrent un-reject can't have the row deleted."""
    service.table("quiz_variant_questions").delete().eq(
        "question_id", question_id
    ).eq("tenant_id", tenant_id).execute()
    service.table("questions").delete().eq("id", question_id).eq(
        "tenant_id", tenant_id
    ).eq("review_status", "rejected").execute()


def purge_rejected_for_quiz_set(
    service, tenant_id: str, created_by: str, quiz_set_id: str
) -> dict[str, int]:
    """Permanently delete rejected questions of a just-published quiz.

    Returns {"purged": n, "kept": m} - kept = rejected questions preserved
    because they were already answered. Best-effort: swallows failures so a
    cleanup problem never undoes a successful publish.
    """
    try:
        rejected_ids = _rejected_question_ids(service, tenant_id, created_by, quiz_set_id)
    except Exception as exc:  # noqa: BLE001 - never fail the publish over cleanup
        log.debug("rejected purge skipped (lookup, %s)", type(exc).__name__)
        return {"purged": 0, "kept": 0}

    purged: list[str] = []
    kept = 0
    for question_id in rejected_ids:
        try:
            if _was_ever_answered(service, question_id):
                kept += 1
                continue
            _delete_question(service, tenant_id, question_id)
            purged.append(question_id)
        except Exception as exc:  # noqa: BLE001 - skip this one, keep going
            log.debug("rejected purge skipped one (%s)", type(exc).__name__)

    if purged:
        log_events(
            [
                make_event(
                    tenant_id=tenant_id,
                    event_type=QUESTION_PURGED,
                    actor_id=created_by,
                    subject_type="question",
                    subject_id=question_id,
                    metadata={"quiz_set_id": quiz_set_id},
                )
                for question_id in purged
            ]
        )
    return {"purged": len(purged), "kept": kept}
