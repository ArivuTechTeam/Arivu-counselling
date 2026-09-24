"""Snapshot approved PYQ into the student-facing library (Phase 1 / PYQ-C).

At publish time each approved is_pyq question of a set is frozen into
`paper_questions`: subject-scoped (for student delivery), de-duplicated (same
content + year + exam is one entry per tenant), and completeness-gated (a PYQ
with no valid answer stays in the quiz but never enters the student pool).

Best-effort: a snapshot failure must never break publishing.
"""

from __future__ import annotations

import hashlib
import json
import logging

from app.lib.config import get_settings
from app.lib.supabase_queries import select_all, select_all_in
from app.services.question_validation import validate_question_answer_shape

logger = logging.getLogger(__name__)


def _content_hash(question: dict) -> str:
    """A stable fingerprint of the question CONTENT (not its metadata), so the same
    question from two uploads collapses to one library entry."""
    payload = json.dumps(
        {
            "t": " ".join((question.get("question_text") or "").split()).lower(),
            "o": question.get("options"),
            "a": question.get("correct_answer"),
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_answerable(question: dict) -> bool:
    """A paper question must be gradeable to enter the student bank. Objective types
    need a valid answer/option shape; a descriptive question needs a model answer /
    summary (it is graded by AI). Otherwise it stays in the quiz for the teacher to
    fix but is excluded from the pool."""
    if (question.get("type") or "") == "descriptive":
        return bool((question.get("answer_summary") or question.get("model_answer") or "").strip())
    try:
        validate_question_answer_shape(
            question.get("type"), question.get("options"), question.get("correct_answer")
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def snapshot_published_pyq(service, tenant_id: str, quiz_set_id: str, actor_id: str) -> int:
    """Freeze the approved is_pyq questions of a just-published set into the PYQ
    library. Returns the number added. Never raises."""
    if not getattr(get_settings(), "paper_bank_enabled", False):
        return 0
    try:
        qset = (
            service.table("quiz_sets").select("id, subject_id, document_id")
            .eq("id", quiz_set_id).eq("tenant_id", tenant_id).maybe_single().execute().data
        )
        subject_id = (qset or {}).get("subject_id")
        if not qset or not subject_id:
            return 0  # no subject to scope PYQ to (student delivery is subject-wise)

        # Re-snapshot this quiz from scratch, so edits / un-marking / rejections
        # since the last publish are reflected. Other quizzes' entries are untouched.
        service.table("paper_questions").delete() \
            .eq("tenant_id", tenant_id).eq("source_quiz_set_id", quiz_set_id).execute()

        variants = select_all(
            service, "quiz_variants", "id",
            configure=lambda q: q.eq("quiz_set_id", quiz_set_id).eq("tenant_id", tenant_id),
        )
        variant_ids = [v["id"] for v in variants]
        if not variant_ids:
            return 0
        links = select_all_in(
            service, "quiz_variant_questions", "question_id",
            in_column="variant_id", values=variant_ids,
            configure=lambda q: q.eq("tenant_id", tenant_id),
        )
        question_ids = list({str(link["question_id"]) for link in links})
        if not question_ids:
            return 0
        questions = select_all_in(
            service, "questions",
            "id, type, question_text, options, correct_answer, explanation, marks, "
            "paper_type, paper_year, paper_exam, chapter_id, model_answer, answer_summary, review_status",
            in_column="id", values=question_ids,
            configure=lambda q: q.eq("tenant_id", tenant_id),
        )

        added = 0
        for q in questions:
            if q.get("review_status") != "approved" or not q.get("paper_type"):
                continue
            if not _is_answerable(q):
                continue  # completeness gate: never show an ungradeable paper to a student
            row = {
                "tenant_id": tenant_id,
                "paper_type": q.get("paper_type"),
                "subject_id": subject_id,
                "chapter_id": q.get("chapter_id"),
                "year": q.get("paper_year") or None,
                "exam": q.get("paper_exam") or None,
                "model_answer": q.get("model_answer"),
                "answer_summary": q.get("answer_summary"),
                "type": q.get("type"),
                "question_text": q.get("question_text"),
                "options": q.get("options"),
                "correct_answer": q.get("correct_answer"),
                "explanation": q.get("explanation"),
                "marks": q.get("marks") or 1,
                "content_hash": _content_hash(q),
                "origin_question_id": q.get("id"),
                "source_quiz_set_id": quiz_set_id,
                "source_document_id": (qset or {}).get("document_id"),
                "created_by": actor_id,
            }
            try:
                service.table("paper_questions").insert(row).execute()
                added += 1
            except Exception:  # noqa: BLE001 - unique index => already in the library (dedup)
                pass
        return added
    except Exception:  # noqa: BLE001 - snapshot is best-effort; never break publish
        logger.warning("PYQ snapshot failed for quiz_set %s", quiz_set_id)
        return 0
