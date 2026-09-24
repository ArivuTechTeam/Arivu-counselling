"""
Question review API (Slice 4).

  PATCH /api/v1/questions/{id}            — edit a question's content
  POST  /api/v1/questions/{id}/approve    — mark approved (stamps reviewer)
  POST  /api/v1/questions/{id}/reject     — mark rejected (stamps reviewer)
  POST  /api/v1/questions/{id}/regenerate — AI rewrites the question in place
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_teacher
from app.lib.api_errors import public_error
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.events import (
    QUESTION_APPROVED,
    QUESTION_EDITED,
    QUESTION_REGENERATED,
    QUESTION_REJECTED,
    log_event,
)
from app.services.llm import LLMError
from app.services.rate_limit import (
    QUESTION_EXPLAIN,
    QUESTION_REGENERATE,
    enforce_ai_rate_limit,
)
from app.services.question_validation import validate_question_answer_shape
from app.services.review import RegenerationSourceError, regenerate_question
from app.services.student_access import student_has_graded_question
from app.services.tutor import explain_question
from app.services import quiz_reuse
from app.services.tenant_features import require_profile_feature

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])

def _assert_teacher_question(
    service, question_id: str, profile: CurrentProfile, *, editing: bool = True
) -> None:
    question = (
        service.table("questions")
        .select("id,release_locked" if quiz_reuse.enabled(profile) else "id")
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if question is None or not question.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    if editing:
        quiz_reuse.assert_editable(question.data)


class QuestionEdit(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    question_text: str | None = Field(default=None, min_length=1)
    options: list[dict] | None = None
    correct_answer: Any | None = None
    explanation: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    marks: float | None = Field(default=None, gt=0)


class QuestionApproval(BaseModel):
    resolution_note: str | None = Field(default=None, max_length=2000)


class QuestionOut(BaseModel):
    content_version: int | None = None
    release_locked: bool = False
    id: str
    type: str
    question_text: str
    options: list[dict] | None = None
    correct_answer: Any
    explanation: str | None = None
    difficulty: str
    marks: float
    review_status: str
    source_excerpt: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    grounding_confidence: float | None = None
    verification_status: str | None = None
    verification_warnings: list[str] = Field(default_factory=list)
    confidence_score: float | None = None
    source: str | None = None
    figure_id: str | None = None
    figure: dict | None = None


class QuestionFigureUpdate(BaseModel):
    # null clears the attached figure; a value attaches one of the question's
    # source-document figures (validated below).
    figure_id: str | None = None


def _match_review_snapshot(query, row: dict):
    """Do not approve or overwrite content changed after the server read it.

    Compare the JSONB answer/options as JSON, including string answers. Keep
    tenant/owner filters on the caller's query as well as these state filters.
    """
    json_fields = {"options", "correct_answer", "verification_warnings"}
    for field in (
        "question_text", "type", "options", "correct_answer", "explanation",
        "verification_status", "verification_warnings", "review_status",
    ):
        value = row.get(field)
        if value is None:
            query = query.is_(field, "null")
        else:
            expected = json.dumps(value, ensure_ascii=False) if field in json_fields else value
            query = query.eq(field, expected)
    if row.get("content_version") is not None:
        query = query.eq("content_version", row["content_version"])
    return query


@router.patch("/{question_id}", response_model=QuestionOut)
def edit_question(
    question_id: str,
    body: QuestionEdit,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_teacher(profile, action="review questions")
    # Only update the fields the teacher actually sent.
    updates = body.model_dump(exclude_unset=True)
    expected_version = updates.pop("expected_version", None)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )
    service = get_service_client()
    existing = (
        service.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if existing is None or not existing.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    if quiz_reuse.enabled(profile):
        quiz_reuse.assert_editable(existing.data)
        if expected_version != existing.data.get("content_version"):
            raise HTTPException(409, "This question changed or the editor is outdated. Reload before saving.")

    # The browser renders a missing explanation as an empty textarea. Treat
    # that round-trip as unchanged, rather than clearing verification on save.
    changed_fields = {}
    for key, value in updates.items():
        previous = existing.data.get(key)
        if key == "explanation" and not value and not previous:
            continue
        if value != previous:
            changed_fields[key] = value
    updates = changed_fields
    if not updates:
        return existing.data
    edited_fields = list(updates)

    # Validate the complete post-edit shape. A partial PATCH may change only
    # options or only the answer, so validating the request body by itself is
    # insufficient and could leave a question the deterministic grader can no
    # longer score correctly.
    try:
        validate_question_answer_shape(
            existing.data["type"],
            updates.get("options", existing.data.get("options")),
            updates.get("correct_answer", existing.data.get("correct_answer")),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid answer configuration: {exc}.",
        ) from exc

    # Only actual content changes invalidate the prior verification. Saving an
    # unchanged form must never clear a blocked status or erase an approval.
    if any(
        field in updates
        for field in ("question_text", "options", "correct_answer", "explanation")
    ):
        prior_warnings = existing.data.get("verification_warnings") or []
        updates["verification_status"] = "needs_teacher_review"
        updates["verification_warnings"] = [
            *prior_warnings,
            "Question was edited after automatic verification; confirm it against the source evidence.",
        ]
        updates["review_status"] = "pending_review"
        updates["reviewed_by"] = None
        updates["reviewed_at"] = None

    update_query = (
        service.table("questions")
        .update(updates)
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)  # tenant guard
        .eq("created_by", profile.user_id)
    )
    updated = _match_review_snapshot(update_query, existing.data).execute()
    if not updated.data:
        raise HTTPException(status_code=409, detail="This question changed while you were editing. Reload it and review the latest version.")
    # Instrument: which fields the teacher changed (powers "approved without
    # edits" and "what do teachers fix most").
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_EDITED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
        metadata={"edited_fields": edited_fields},
    )
    return updated.data[0]


def _question_document_id(service, question_id: str, tenant_id: str) -> str | None:
    """The source document of the question's quiz set (tenant-scoped), or None."""
    link = (
        service.table("quiz_variant_questions")
        .select("variant_id")
        .eq("question_id", question_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not link or not link.data:
        return None
    variant = (
        service.table("quiz_variants")
        .select("quiz_set_id")
        .eq("id", link.data["variant_id"])
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not variant or not variant.data:
        return None
    quiz_set = (
        service.table("quiz_sets")
        .select("document_id")
        .eq("id", variant.data["quiz_set_id"])
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    return (quiz_set.data or {}).get("document_id") if quiz_set else None


@router.put("/{question_id}/figure", response_model=QuestionOut)
def set_question_figure(
    question_id: str,
    body: QuestionFigureUpdate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Teacher confirms/swaps/removes the figure attached to a question.

    `figure_id = null` removes it. A non-null id must be a figure of THIS
    question's own source document (never another document/tenant), so a teacher
    can only choose among the figures the source PDF actually contains.
    """
    require_teacher(profile, action="edit question figures")
    require_profile_feature(profile, "figure_attach", label="Question figures")
    service = get_service_client()
    _assert_teacher_question(service, question_id, profile)

    figure_id = body.figure_id
    figure: dict | None = None
    if figure_id:
        document_id = _question_document_id(service, question_id, profile.tenant_id)
        if not document_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This question is not linked to source material with figures.",
            )
        candidate = (
            service.table("document_figures")
            .select("id, document_id")
            .eq("id", figure_id)
            .eq("tenant_id", profile.tenant_id)
            .maybe_single()
            .execute()
        )
        if candidate is None or not candidate.data:
            raise HTTPException(status_code=404, detail="Figure not found.")
        if candidate.data.get("document_id") != document_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That figure belongs to a different document.",
            )

    updated = (
        service.table("questions")
        .update({"figure_id": figure_id})
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Question not found.")

    if figure_id:
        from app.services.document_figures import figures_for_questions

        figure = figures_for_questions(
            service, tenant_id=profile.tenant_id, figure_ids=[figure_id]
        ).get(figure_id)

    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_EDITED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
        metadata={"edited_fields": ["figure_id"], "figure_attached": bool(figure_id)},
    )
    return {**updated.data[0], "figure": figure}


def _set_review_status(
    question_id: str, profile: CurrentProfile, review_status: str
) -> dict:
    service = get_service_client()
    _assert_teacher_question(service, question_id, profile)
    updated = (
        service.table("questions")
        .update(
            {
                "review_status": review_status,
                "reviewed_by": profile.user_id,
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    return updated.data[0]


@router.post("/{question_id}/approve", response_model=QuestionOut)
def approve_question(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
    body: QuestionApproval | None = None,
) -> dict:
    require_teacher(profile, action="review questions")
    service = get_service_client()
    question = (
        service.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("created_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if not question or not question.data:
        raise HTTPException(status_code=404, detail="Question not found.")
    row = question.data
    quiz_reuse.assert_editable(row)
    if row.get("review_status") == "approved":
        return row
    note = (body.resolution_note or "").strip() if body else ""
    try:
        validate_question_answer_shape(row["type"], row.get("options"), row.get("correct_answer"))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Correct the answer before approval: {exc}") from exc
    reviewed_at = datetime.now(timezone.utc).isoformat()
    updates = {"review_status": "approved", "reviewed_by": profile.user_id, "reviewed_at": reviewed_at}
    if note:
        # Persist the resolution with the approval itself; analytics events are
        # best-effort and must not be the only copy of the teacher's decision.
        updates["verification_warnings"] = [
            *(row.get("verification_warnings") or []),
            f"Teacher resolution ({profile.user_id}, {reviewed_at}): {note}",
        ]
    update_query = (service.table("questions").update(updates)
                    .eq("id", question_id).eq("tenant_id", profile.tenant_id)
                    .eq("created_by", profile.user_id))
    updated = _match_review_snapshot(update_query, row).execute()
    if not updated.data:
        raise HTTPException(status_code=409, detail="This question changed during review. Reload it before approving.")
    result = updated.data[0]
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_APPROVED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
        metadata={"verification_status": row.get("verification_status"), "individual_resolution": bool(note)},
    )
    return result


@router.post("/{question_id}/reject", response_model=QuestionOut)
def reject_question(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_teacher(profile, action="review questions")
    result = _set_review_status(question_id, profile, "rejected")
    log_event(
        tenant_id=profile.tenant_id,
        event_type=QUESTION_REJECTED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="question",
        subject_id=question_id,
    )
    return result


@router.post("/{question_id}/regenerate", response_model=QuestionOut)
def regenerate(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    require_teacher(profile, action="review questions")
    service = get_service_client()
    _assert_teacher_question(service, question_id, profile)
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUESTION_REGENERATE,
        hourly_limit=get_settings().rate_limit_question_regenerate_per_hour,
        action_label="question regeneration",
    )
    try:
        result = regenerate_question(question_id, profile.tenant_id)
        log_event(
            tenant_id=profile.tenant_id,
            event_type=QUESTION_REGENERATED,
            actor_id=profile.user_id,
            actor_role=profile.role,
            subject_type="question",
            subject_id=question_id,
        )
        return result
    except RegenerationSourceError as exc:
        raise public_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This question cannot be regenerated because its original source "
            "material is unavailable. Edit it manually instead.",
            operation="load regeneration source material",
            exception=exc,
        ) from exc
    except ValueError as exc:
        raise public_error(
            404,
            "Question not found.",
            operation="regenerate question lookup",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't regenerate this question right now. Please try again.",
            operation="regenerate question with AI",
            exception=exc,
        ) from exc


@router.post("/{question_id}/explain")
def explain(
    question_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    AI Tutor: a deeper step-by-step explanation + a simplified version + hints,
    cached per question in ai_explanations. Teachers may explain their own
    questions; students gain access only after the question has been graded.
    """
    if profile.role not in {"teacher", "student"}:
        raise HTTPException(status_code=403, detail="Teachers and students only.")
    service = get_service_client()
    if profile.role == "teacher":
        _assert_teacher_question(service, question_id, profile, editing=False)
    elif not student_has_graded_question(service, question_id, profile):
        raise HTTPException(
            status_code=403,
            detail="Explanations are available after you submit this question.",
        )
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUESTION_EXPLAIN,
        hourly_limit=get_settings().rate_limit_question_explain_per_hour,
        action_label="question explanations",
    )
    try:
        return explain_question(question_id, profile.tenant_id)
    except ValueError as exc:
        raise public_error(
            404,
            "Question not found.",
            operation="explain question lookup",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't generate an explanation right now. Please try again.",
            operation="explain question with AI",
            exception=exc,
        ) from exc
