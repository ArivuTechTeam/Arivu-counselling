"""
Student quiz-taking API (Slice 5).

  GET  /api/v1/quizzes                  — published quizzes available to take
  POST /api/v1/attempts                 — start an attempt for a variant
  GET  /api/v1/attempts/{id}            — load an attempt
                                          (in_progress: answers HIDDEN;
                                           graded: results + score)
  POST /api/v1/attempts/{id}/submit     — submit answers, auto-grade, score
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.config import get_settings
from app.lib.pagination import (
    DEFAULT_PAGE_SIZE,
    bounded_page_size,
    decode_cursor,
    encode_cursor,
)
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import rpc_json_value, select_all, select_all_in
from app.services.attempt_timing import (
    deadline_state,
    effective_time_limit_minutes,
    is_answered,
    taking_questions,
    timing_payload,
)
from app.services.events import ATTEMPT_SUBMITTED, log_event
from app.services.scoring import normalize_policy, score
from app.services.batch_access import student_can_access_quiz
from app.services.tenant_features import profile_feature_enabled

router = APIRouter(prefix="/api/v1", tags=["student"])


class StudentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentVariantOut(StudentResponse):
    id: str
    variant_type: str
    total_marks: float | None = None
    time_limit_minutes: float | None = None
    question_count: int
    attempted: bool
    attempt_count: int
    attempt_limit: int
    attempts_remaining: int
    best_pct: int | None = None


class StudentQuizOut(StudentResponse):
    id: str
    title: str
    published_at: datetime | None = None
    subject_id: str | None = None
    chapter_id: str | None = None
    subject_name: str | None = None
    chapter_name: str | None = None
    variants: list[StudentVariantOut]


class StudentQuizPage(StudentResponse):
    items: list[StudentQuizOut]
    next_cursor: str | None = None


class StudentQuizSearchRequest(StudentResponse):
    cursor: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    subject_id: str | None = None
    chapter_id: str | None = None
    assignment: Literal["all", "course", "assigned"] = "all"
    query: str = Field(default="", max_length=100)


class AttemptHistoryOut(StudentResponse):
    attempt_id: str
    quiz_title: str
    variant_id: str | None = None
    variant_type: str | None = None
    subject_id: str | None = None
    chapter_id: str | None = None
    total_score: float | None = None
    max_score: float | None = None
    submitted_at: datetime
    source: Literal["quiz", "practice"]


class AttemptHistoryPage(StudentResponse):
    items: list[AttemptHistoryOut]
    next_cursor: str | None = None


class TakingQuestionOut(StudentResponse):
    id: str
    type: str
    question_text: str
    options: Any = None
    marks: float | None = None
    suggested_seconds: int | None = None
    figure_id: str | None = None


class AttemptInProgressOut(StudentResponse):
    attempt_id: str
    status: Literal["in_progress"]
    questions: list[TakingQuestionOut]
    autosave_state: dict[str, Any]
    time_limit_minutes: float | None = None
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    remaining_seconds: int | None = None


class ResultQuestionOut(TakingQuestionOut):
    correct_answer: Any
    explanation: str | None = None
    student_answer: Any = None
    is_correct: bool | None = None
    marks_awarded: float | None = None


class AttemptResultOut(StudentResponse):
    attempt_id: str
    status: str
    quiz_title: str
    total_score: float
    max_score: float
    results: list[ResultQuestionOut]


class AutosaveOut(StudentResponse):
    saved: bool


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can take quizzes.",
        )


QUESTION_ATTEMPT_COLUMNS = (
    "id, type, question_text, options, correct_answer, explanation, marks, figure_id"
)


# The ordinary quiz-taking flow can only score objective questions. A descriptive
# question (extracted in paper mode) would get the wrong answer box and always
# score 0, so it is left out of what students take and out of every denominator.
# Descriptive questions are still graded where they belong: the paper-bank flow.
def _without_descriptive(questions: list[dict]) -> list[dict]:
    return [q for q in questions if q.get("type") != "descriptive"]


def _ordered_approved_questions(
    service, variant_id: str, tenant_id: str
) -> list[dict]:
    """The variant's APPROVED, student-answerable questions, in the teacher's order."""
    links = (
        service.table("quiz_variant_questions")
        .select("question_id, order_index, marks_override")
        .eq("variant_id", variant_id)
        .eq("tenant_id", tenant_id)
        .order("order_index")
        .execute()
        .data
        or []
    )
    ids = [link["question_id"] for link in links]
    if not ids:
        return []
    rows = (
        service.table("questions")
        .select(QUESTION_ATTEMPT_COLUMNS)
        .in_("id", ids)
        .eq("tenant_id", tenant_id)
        .eq("review_status", "approved")
    )
    rows = rows.execute().data or []
    by_id = {row["id"]: row for row in rows}
    ordered = []
    for link in links:
        question = by_id.get(link["question_id"])
        if question is None:
            continue
        effective_question = dict(question)
        if link.get("marks_override") is not None:
            effective_question["marks"] = link["marks_override"]
        ordered.append(effective_question)
    return _without_descriptive(ordered)


def _attempt_questions(service, attempt: dict, tenant_id: str) -> list[dict]:
    """Return the immutable paper saved at start, with a legacy fallback."""
    snapshot = attempt.get("question_snapshot")
    if isinstance(snapshot, list) and snapshot:
        # Attempts frozen before this rule still hold descriptive questions.
        return _without_descriptive(snapshot)
    return _ordered_approved_questions(service, attempt["variant_id"], tenant_id)


def _strip_answer(q: dict) -> dict:
    """What a student is allowed to SEE while taking — no correct_answer/why."""
    return {
        "id": q["id"],
        "type": q["type"],
        "question_text": q["question_text"],
        "options": q.get("options"),
        "marks": q.get("marks"),
        "figure_id": q.get("figure_id"),
    }


def _quiz_title_for_variant(
    service, variant_id: str, tenant_id: str
) -> str:
    variant = (
        service.table("quiz_variants")
        .select("quiz_set_id")
        .eq("id", variant_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if variant is None or not variant.data:
        return "Quiz"
    quiz_set = (
        service.table("quiz_sets")
        .select("title")
        .eq("id", variant.data["quiz_set_id"])
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if quiz_set and quiz_set.data and quiz_set.data.get("title"):
        return quiz_set.data["title"]
    return "Quiz"


def list_quizzes(
    profile: CurrentProfile = Depends(get_current_profile),
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    subject_id: str | None = None,
    chapter_id: str | None = None,
    assignment: Literal["all", "course", "assigned"] = "all",
    q: str = "",
) -> StudentQuizPage:
    _require_student(profile)
    page_size = bounded_page_size(page_size)
    page_cursor = decode_cursor(cursor)
    normalized_query = q.strip()
    if len(normalized_query) > 100:
        raise HTTPException(status_code=400, detail="Search text is too long.")
    settings = get_settings()
    batches_on = (
        getattr(settings, "batches_enabled", False)
        if profile.tenant_feature_flags is None
        else profile_feature_enabled(profile, "batches")
    )
    rows = rpc_json_value(
        get_service_client(),
        "student_quiz_catalog_page",
        {
            "p_tenant": profile.tenant_id,
            "p_student": profile.user_id,
            "p_limit": page_size + 1,
            "p_attempt_limit": settings.student_quiz_attempt_limit,
            "p_batches_enabled": batches_on,
            "p_before_at": page_cursor.occurred_at.isoformat() if page_cursor else None,
            "p_before_id": page_cursor.row_id if page_cursor else None,
            "p_subject": subject_id,
            "p_chapter": chapter_id,
            "p_assignment": assignment,
            "p_search": normalized_query or None,
        },
        list,
    )
    has_more = len(rows) > page_size
    items = rows[:page_size]
    next_cursor = (
        encode_cursor(items[-1]["_cursor_at"], items[-1]["id"])
        if has_more and items
        else None
    )
    for item in items:
        item.pop("_cursor_at", None)
    return StudentQuizPage(items=items, next_cursor=next_cursor)


@router.get("/quizzes", response_model=StudentQuizPage)
def list_quizzes_route(
    profile: CurrentProfile = Depends(get_current_profile),
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    subject_id: str | None = None,
    chapter_id: str | None = None,
    assignment: Literal["all", "course", "assigned"] = "all",
) -> StudentQuizPage:
    """List without free text so private searches never enter a request URL."""
    return list_quizzes(
        profile=profile,
        cursor=cursor,
        page_size=page_size,
        subject_id=subject_id,
        chapter_id=chapter_id,
        assignment=assignment,
    )


@router.post("/quizzes/search", response_model=StudentQuizPage)
def search_quizzes(
    body: StudentQuizSearchRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> StudentQuizPage:
    return list_quizzes(
        profile=profile,
        cursor=body.cursor,
        page_size=body.page_size,
        subject_id=body.subject_id,
        chapter_id=body.chapter_id,
        assignment=body.assignment,
        q=body.query,
    )


class StartAttemptRequest(BaseModel):
    variant_id: str


def _resolve_quiz_scoring_policy(
    service, quiz_set_id: str, profile: CurrentProfile
) -> dict | None:
    """The rules of a quiz's attached scoring policy, or None (default full/zero).
    Gated by SCORING_POLICIES_ENABLED, so scoring is unchanged until it's on."""
    scoring_enabled = (
        getattr(get_settings(), "scoring_policies_enabled", False)
        if profile.tenant_feature_flags is None
        else profile_feature_enabled(profile, "scoring_policies")
    )
    if not scoring_enabled:
        return None
    tenant_id = profile.tenant_id
    quiz = (
        service.table("quiz_sets").select("scoring_policy_id")
        .eq("id", quiz_set_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    policy_id = (quiz.data or {}).get("scoring_policy_id") if quiz else None
    if not policy_id:
        return None
    row = (
        service.table("scoring_policies").select("rules")
        .eq("id", policy_id).eq("tenant_id", tenant_id).maybe_single().execute()
    )
    return (row.data or {}).get("rules") if row else None


@router.post("/attempts", response_model=AttemptInProgressOut)
def start_attempt(
    body: StartAttemptRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt_limit = get_settings().student_quiz_attempt_limit

    variant = (
        service.table("quiz_variants")
        .select("id, quiz_set_id, time_limit_minutes")
        .eq("id", body.variant_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if variant is None or not variant.data:
        raise HTTPException(status_code=404, detail="Quiz variant not found.")

    # Access gate (single source of truth): the quiz must be published and either
    # a legacy_course quiz in an enrolled subject or an assigned_batches quiz the
    # student can reach via batch assignment. With BATCHES_ENABLED off this is
    # exactly the legacy course-subject rule.
    if not student_can_access_quiz(service, profile, variant.data["quiz_set_id"]):
        raise HTTPException(
            status_code=403,
            detail="This quiz is not available to you.",
        )

    previous_attempts = (
        service.table("quiz_attempts")
        .select("id")
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("variant_id", body.variant_id)
        .execute()
        .data
        or []
    )
    if len(previous_attempts) >= attempt_limit:
        raise HTTPException(
            status_code=400,
            detail=f"You have already used all {attempt_limit} attempts for this quiz.",
        )

    questions = _ordered_approved_questions(
        service, body.variant_id, profile.tenant_id
    )
    if not questions:
        raise HTTPException(
            status_code=400,
            detail="This quiz does not have any approved questions yet.",
        )

    time_limit = effective_time_limit_minutes(
        questions, variant.data.get("time_limit_minutes")
    )
    scoring_policy = _resolve_quiz_scoring_policy(
        service, variant.data["quiz_set_id"], profile
    )
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        if hasattr(service, "rpc"):
            created = service.rpc(
                "create_limited_quiz_attempt",
                {
                    "p_tenant_id": profile.tenant_id,
                    "p_variant_id": body.variant_id,
                    "p_student_id": profile.user_id,
                    "p_started_at": started_at,
                    "p_max_attempts": attempt_limit,
                    "p_question_snapshot": questions,
                    "p_scoring_policy_snapshot": scoring_policy,
                },
            ).execute()
            attempt_id = str(created.data)
        else:  # lightweight in-memory test clients
            attempt = (
                service.table("quiz_attempts")
                .insert(
                    {
                        "tenant_id": profile.tenant_id,
                        "variant_id": body.variant_id,
                        "student_id": profile.user_id,
                        "status": "in_progress",
                        "started_at": started_at,
                        "question_snapshot": questions,
                        "scoring_policy_snapshot": scoring_policy,
                    }
                )
                .execute()
            )
            attempt_id = attempt.data[0]["id"]
    except Exception as exc:
        if "quiz_attempt_limit_reached" in str(exc):
            raise HTTPException(
                status_code=400,
                detail=f"You have already used all {attempt_limit} attempts for this quiz.",
            ) from exc
        raise
    # These questions were already loaded to validate the quiz. Return the
    # answer-stripped taking state so the client can render immediately instead
    # of repeating the attempt + link + question queries after navigation.
    return {
        "attempt_id": attempt_id,
        "status": "in_progress",
        "questions": taking_questions(
            [_strip_answer(question) for question in questions],
            time_limit,
        ),
        "autosave_state": {},
        **timing_payload(started_at, time_limit),
    }


def _load_attempt(service, attempt_id: str, profile: CurrentProfile) -> dict:
    attempt = (
        service.table("quiz_attempts")
        .select("*")
        .eq("id", attempt_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)  # a student only sees their own
        .maybe_single()
        .execute()
    )
    if attempt is None or not attempt.data:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    return attempt.data


@router.get(
    "/attempts/{attempt_id}",
    response_model=AttemptInProgressOut | AttemptResultOut,
)
def get_attempt(
    attempt_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt = _load_attempt(service, attempt_id, profile)
    questions = _attempt_questions(service, attempt, profile.tenant_id)
    variant = (
        service.table("quiz_variants")
        .select("time_limit_minutes")
        .eq("id", attempt["variant_id"])
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    time_limit = effective_time_limit_minutes(
        questions,
        (variant.data or {}).get("time_limit_minutes") if variant else None,
    )

    if attempt["status"] == "in_progress":
        return {
            "attempt_id": attempt_id,
            "status": "in_progress",
            "questions": taking_questions(
                [_strip_answer(q) for q in questions], time_limit
            ),
            "autosave_state": attempt.get("autosave_state") or {},
            **timing_payload(attempt.get("started_at"), time_limit),
        }

    # Graded: return full results (answers now allowed).
    answers = (
        service.table("attempt_answers")
        .select("*")
        .eq("attempt_id", attempt_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    by_qid = {a["question_id"]: a for a in answers}
    results = []
    for q in questions:
        a = by_qid.get(q["id"], {})
        results.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question_text": q["question_text"],
                "options": q.get("options"),
                "correct_answer": q["correct_answer"],
                "explanation": q.get("explanation"),
                "marks": q.get("marks"),
                "figure_id": q.get("figure_id"),
                "student_answer": a.get("student_answer"),
                "is_correct": a.get("is_correct"),
                "marks_awarded": a.get("marks_awarded"),
            }
        )
    max_score = sum(float(q.get("marks") or 1) for q in questions)
    # Quiz title (for the downloadable report card / question paper header).
    quiz_title = _quiz_title_for_variant(
        service, attempt["variant_id"], profile.tenant_id
    )
    return {
        "attempt_id": attempt_id,
        "status": attempt["status"],
        "quiz_title": quiz_title,
        "total_score": attempt["total_score"],
        "max_score": max_score,
        "results": results,
    }


class SubmittedAnswer(BaseModel):
    question_id: str
    student_answer: Any = None


class SubmitRequest(BaseModel):
    answers: list[SubmittedAnswer]
    finalize_reason: Literal["submit", "left"] = "submit"


class AutosaveRequest(BaseModel):
    answers: dict[str, Any]


@router.patch("/attempts/{attempt_id}/autosave", response_model=AutosaveOut)
def autosave_attempt(
    attempt_id: str,
    body: AutosaveRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt = _load_attempt(service, attempt_id, profile)
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="This attempt is already submitted.")
    variant = (
        service.table("quiz_variants")
        .select("time_limit_minutes")
        .eq("id", attempt["variant_id"])
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    questions = _attempt_questions(service, attempt, profile.tenant_id)
    time_limit = effective_time_limit_minutes(
        questions,
        (variant.data or {}).get("time_limit_minutes") if variant else None,
    )
    deadline = deadline_state(
        attempt.get("started_at"),
        time_limit,
    )
    if deadline and deadline.beyond_grace:
        raise HTTPException(status_code=400, detail="This quiz has ended.")
    allowed = {
        q["id"]
        for q in questions
    }
    answers = {key: value for key, value in body.answers.items() if key in allowed}
    service.table("quiz_attempts").update({"autosave_state": answers}).eq(
        "id", attempt_id
    ).eq("tenant_id", profile.tenant_id).eq(
        "student_id", profile.user_id
    ).execute()
    return {"saved": True}


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptResultOut)
def submit_attempt(
    attempt_id: str,
    body: SubmitRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt = _load_attempt(service, attempt_id, profile)
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="This attempt is already submitted.")

    questions = _attempt_questions(service, attempt, profile.tenant_id)
    submitted = {a.question_id: a.student_answer for a in body.answers}
    variant = (
        service.table("quiz_variants")
        .select("time_limit_minutes")
        .eq("id", attempt["variant_id"])
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    time_limit = effective_time_limit_minutes(
        questions,
        (variant.data or {}).get("time_limit_minutes") if variant else None,
    )
    deadline = deadline_state(
        attempt.get("started_at"),
        time_limit,
    )
    if deadline and deadline.beyond_grace:
        submitted = dict(attempt.get("autosave_state") or {})
    elif body.finalize_reason != "left" and not (deadline and deadline.reached):
        missing = [
            q["id"] for q in questions if not is_answered(submitted.get(q["id"]))
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="Answer every question before submitting.",
            )

    # Scoring policy frozen at attempt start (None = default full/zero, which the
    # engine reproduces exactly via grade_answer).
    policy = attempt.get("scoring_policy_snapshot")
    total = 0.0
    results = []
    answer_rows = []
    for q in questions:
        student_answer = submitted.get(q["id"])
        outcome = score(q, student_answer, policy)
        is_correct = outcome.state == "correct"
        awarded = outcome.awarded
        total += awarded
        answer_rows.append(
            {
                "tenant_id": profile.tenant_id,
                "attempt_id": attempt_id,
                "question_id": q["id"],
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        )
        results.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question_text": q["question_text"],
                "options": q.get("options"),
                "correct_answer": q["correct_answer"],
                "explanation": q.get("explanation"),
                "marks": q.get("marks"),
                "figure_id": q.get("figure_id"),
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        )

    if policy is not None and normalize_policy(policy)["clamp_negative_total"]:
        total = max(0.0, total)  # negative-marking exams never drop below zero

    submitted_at = datetime.now(timezone.utc).isoformat()
    claimed = (
        service.table("quiz_attempts")
        .update(
            {
                "status": "graded",
                "total_score": total,
                "submitted_at": submitted_at,
                "autosave_state": {},
            }
        )
        .eq("id", attempt_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("status", "in_progress")
        .execute()
    )
    if not claimed.data:
        raise HTTPException(status_code=400, detail="This attempt is already submitted.")
    try:
        if answer_rows:
            service.table("attempt_answers").upsert(
                answer_rows, on_conflict="attempt_id,question_id"
            ).execute()
    except Exception as exc:  # noqa: BLE001
        # Compensate so a failed answer write never leaves a graded attempt
        # with missing results. The status predicate also makes retries safe.
        service.table("attempt_answers").delete().eq("attempt_id", attempt_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
        service.table("quiz_attempts").update(
            {
                "status": "in_progress",
                "total_score": None,
                "submitted_at": None,
            }
        ).eq("id", attempt_id).eq("tenant_id", profile.tenant_id).eq(
            "student_id", profile.user_id
        ).execute()
        raise public_error(
            500,
            "We couldn't save your answers. Your attempt is still open; please try again.",
            operation="save submitted quiz answers",
            exception=exc,
        ) from exc

    max_score = sum(float(q.get("marks") or 1) for q in questions)
    # Instrument: a graded attempt (powers student-outcome trends).
    pct = round(total / max_score * 100) if max_score else 0
    log_event(
        tenant_id=profile.tenant_id,
        event_type=ATTEMPT_SUBMITTED,
        actor_id=profile.user_id,
        actor_role=profile.role,
        subject_type="attempt",
        subject_id=attempt_id,
        metadata={
            "variant_id": attempt["variant_id"],
            "score_pct": pct,
            "questions": len(questions),
            "score": total,
            "max": max_score,
        },
    )
    return {
        "attempt_id": attempt_id,
        "status": "graded",
        "quiz_title": _quiz_title_for_variant(
            service, attempt["variant_id"], profile.tenant_id
        ),
        "total_score": total,
        "max_score": max_score,
        "results": results,
    }


def _student_graded_answers(
    service, tenant_id: str, student_id: str
) -> tuple[list[dict], int]:
    """Return answered questions from graded work across both quiz engines.

    Teacher-published quizzes use quiz_attempts/attempt_answers; Smart Quiz,
    Daily, Exam, Challenge and Revision use practice_sessions/practice_answers.
    Student analytics must combine both or the dashboard contradicts History.
    Grading stores rows for unanswered questions too, so those rows must not
    count as solved or lower answer-based accuracy and topic mastery.
    """
    quiz_attempts = select_all(
        service,
        "quiz_attempts",
        "id",
        configure=lambda query: query.eq("tenant_id", tenant_id)
        .eq("student_id", student_id)
        .eq("status", "graded"),
    )
    practice_sessions = select_all(
        service,
        "practice_sessions",
        "id",
        configure=lambda query: query.eq("tenant_id", tenant_id)
        .eq("student_id", student_id)
        .eq("status", "graded"),
    )

    answers: list[dict] = []
    attempt_ids = [row["id"] for row in quiz_attempts]
    if attempt_ids:
        answers.extend(
            select_all_in(
                service,
                "attempt_answers",
                "question_id, student_answer, is_correct",
                in_column="attempt_id",
                values=attempt_ids,
                configure=lambda query: query.eq("tenant_id", tenant_id),
            )
        )
    session_ids = [row["id"] for row in practice_sessions]
    if session_ids:
        answers.extend(
            select_all_in(
                service,
                "practice_answers",
                "question_id, student_answer, is_correct",
                in_column="session_id",
                values=session_ids,
                configure=lambda query: query.eq("tenant_id", tenant_id),
            )
        )
    answered = [a for a in answers if is_answered(a.get("student_answer"))]
    return answered, len(quiz_attempts) + len(practice_sessions)


@router.get("/student/stats")
def student_stats(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """
    Read-only overview for the student dashboard — all real metrics, no invented
    numbers. Weak areas come from the questions' topic_id tags (the same data the
    v_student_topic_accuracy view is built on).
    """
    _require_student(profile)
    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id

    answers, graded_work_count = _student_graded_answers(service, tid, uid)
    total = len(answers)
    correct = sum(1 for a in answers if a.get("is_correct"))
    accuracy = round(correct / total * 100) if total else 0

    # Accuracy per topic (for the mastery chart) + the 3 weakest for the panel.
    topic_accuracy: list[dict] = []
    if answers:
        qids = list({a["question_id"] for a in answers})
        qrows = select_all_in(
            service,
            "questions",
            "id, topic_id",
            in_column="id",
            values=qids,
            configure=lambda query: query.eq("tenant_id", tid),
        )
        topic_of = {q["id"]: q.get("topic_id") for q in qrows}
        agg: dict[str, tuple[int, int]] = {}
        for a in answers:
            top = topic_of.get(a["question_id"])
            if not top:
                continue
            c, t = agg.get(top, (0, 0))
            agg[top] = (c + (1 if a.get("is_correct") else 0), t + 1)
        if agg:
            names = select_all_in(
                service,
                "topics",
                "id, name",
                in_column="id",
                values=list(agg.keys()),
                configure=lambda query: query.eq("tenant_id", tid),
            )
            name_of = {n["id"]: n["name"] for n in names}
            for top, (c, t) in agg.items():
                topic_accuracy.append(
                    {
                        "topic": name_of.get(top, "Topic"),
                        "accuracy": round(c / t * 100) if t else 0,
                        "attempted": t,
                    }
                )
            topic_accuracy.sort(key=lambda x: x["accuracy"])

    return {
        "quizzes_taken": graded_work_count,
        "questions_solved": total,
        "overall_accuracy": accuracy,
        "weak_areas": [topic for topic in topic_accuracy if topic["accuracy"] < 60][
            :3
        ],
        "topic_accuracy": topic_accuracy,
    }


@router.get("/student/weak-analysis")
def student_weak_analysis(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Hierarchical weak-area analysis for the student: their answered questions
    rolled up Subject -> Chapter -> Topic, with a success rate (% correct) at
    every level, weakest first. All real data — no invented numbers.
    """
    _require_student(profile)
    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id
    empty = {
        "overall": {"accuracy": 0, "answered": 0, "correct": 0, "weak_topics": 0},
        "subjects": [],
    }

    answers, _ = _student_graded_answers(service, tid, uid)
    if not answers:
        return empty

    qids = list({a["question_id"] for a in answers})
    qrows = select_all_in(
        service,
        "questions",
        "id, chapter_id, topic_id",
        in_column="id",
        values=qids,
        configure=lambda query: query.eq("tenant_id", tid),
    )
    qmap = {q["id"]: q for q in qrows}

    chapter_ids = list({q["chapter_id"] for q in qrows if q.get("chapter_id")})
    chapters = (
        select_all_in(
            service,
            "chapters",
            "id, name, subject_id",
            in_column="id",
            values=chapter_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )
        if chapter_ids
        else []
    )
    chmap = {c["id"]: c for c in chapters}
    subject_ids = list({c["subject_id"] for c in chapters})
    subjects = (
        {
            s["id"]: s["name"]
            for s in select_all_in(
                service,
                "subjects",
                "id, name",
                in_column="id",
                values=subject_ids,
                configure=lambda query: query.eq("tenant_id", tid),
            )
        }
        if subject_ids
        else {}
    )
    topic_ids = list({q["topic_id"] for q in qrows if q.get("topic_id")})
    topics = (
        {
            t["id"]: t["name"]
            for t in select_all_in(
                service,
                "topics",
                "id, name",
                in_column="id",
                values=topic_ids,
                configure=lambda query: query.eq("tenant_id", tid),
            )
        }
        if topic_ids
        else {}
    )

    # Nested tally: subject -> chapter -> topic, each a [correct, total] pair.
    UNCAT = "Uncategorised"
    from collections import defaultdict

    def pair() -> list[int]:
        return [0, 0]

    subs_agg: dict = defaultdict(
        lambda: {"n": pair(), "ch": defaultdict(lambda: {"n": pair(), "tp": defaultdict(pair)})}
    )
    for a in answers:
        q = qmap.get(a["question_id"])
        if not q:
            continue
        correct = 1 if a.get("is_correct") else 0
        ch = chmap.get(q.get("chapter_id"))
        if ch:
            sname = subjects.get(ch["subject_id"], "Subject")
            cname = ch["name"]
        else:
            sname, cname = UNCAT, "General"
        tname = topics.get(q["topic_id"]) if q.get("topic_id") else "General"
        s = subs_agg[sname]
        c = s["ch"][cname]
        t = c["tp"][tname]
        for bucket in (s["n"], c["n"], t):
            bucket[0] += correct
            bucket[1] += 1

    def pct(p: list[int]) -> int:
        return round(p[0] / p[1] * 100) if p[1] else 0

    subjects_out = []
    weak_topics = 0
    tot_c = tot_t = 0
    for sname, sd in subs_agg.items():
        tot_c += sd["n"][0]
        tot_t += sd["n"][1]
        chapters_out = []
        for cname, cd in sd["ch"].items():
            topics_out = []
            for tname, tp in cd["tp"].items():
                acc = pct(tp)
                if acc < 60:
                    weak_topics += 1
                topics_out.append({"topic": tname, "accuracy": acc, "answered": tp[1]})
            topics_out.sort(key=lambda x: x["accuracy"])
            chapters_out.append(
                {
                    "chapter": cname,
                    "accuracy": pct(cd["n"]),
                    "answered": cd["n"][1],
                    "topics": topics_out,
                }
            )
        chapters_out.sort(key=lambda x: x["accuracy"])
        subjects_out.append(
            {
                "subject": sname,
                "accuracy": pct(sd["n"]),
                "answered": sd["n"][1],
                "chapters": chapters_out,
            }
        )
    # Weakest subjects first; the Uncategorised bucket always sinks to the bottom.
    subjects_out.sort(key=lambda x: (x["subject"] == UNCAT, x["accuracy"]))

    return {
        "overall": {
            "accuracy": round(tot_c / tot_t * 100) if tot_t else 0,
            "answered": tot_t,
            "correct": tot_c,
            "weak_topics": weak_topics,
        },
        "subjects": subjects_out,
    }


def _flat_weak_topics(service, tid: str, uid: str, threshold: int = 60) -> list[dict]:
    """Flat list of a student's weak topics (accuracy < threshold), weakest first.

    Each item: {key, subject, chapter, topic, accuracy, answered}. `key` uses
    database ids so renaming a subject, chapter or topic does not reset revision.
    """
    from collections import defaultdict

    answers, _ = _student_graded_answers(service, tid, uid)
    if not answers:
        return []
    qids = list({a["question_id"] for a in answers})
    qrows = select_all_in(
        service,
        "questions",
        "id, chapter_id, topic_id",
        in_column="id",
        values=qids,
        configure=lambda query: query.eq("tenant_id", tid),
    )
    qmap = {q["id"]: q for q in qrows}
    chapter_ids = list({q["chapter_id"] for q in qrows if q.get("chapter_id")})
    chapters = (
        select_all_in(
            service,
            "chapters",
            "id, name, subject_id",
            in_column="id",
            values=chapter_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )
        if chapter_ids
        else []
    )
    chmap = {c["id"]: c for c in chapters}
    subject_ids = list({c["subject_id"] for c in chapters})
    subjects = (
        {
            s["id"]: s["name"]
            for s in select_all_in(
                service,
                "subjects",
                "id, name",
                in_column="id",
                values=subject_ids,
                configure=lambda query: query.eq("tenant_id", tid),
            )
        }
        if subject_ids
        else {}
    )
    topic_ids = list({q["topic_id"] for q in qrows if q.get("topic_id")})
    topics = (
        {
            t["id"]: t["name"]
            for t in select_all_in(
                service,
                "topics",
                "id, name",
                in_column="id",
                values=topic_ids,
                configure=lambda query: query.eq("tenant_id", tid),
            )
        }
        if topic_ids
        else {}
    )

    agg: dict = defaultdict(lambda: [0, 0])
    meta: dict = {}
    for a in answers:
        q = qmap.get(a["question_id"])
        if not q:
            continue
        ch = chmap.get(q.get("chapter_id"))
        if ch:
            sname = subjects.get(ch["subject_id"], "Subject")
            cname = ch["name"]
        else:
            sname, cname = "Uncategorised", "General"
        tname = topics.get(q["topic_id"]) if q.get("topic_id") else "General"
        if q.get("topic_id"):
            key = f"topic:{q['topic_id']}"
        elif ch:
            key = f"chapter:{ch['id']}:general"
        else:
            key = "uncategorised:general"
        agg[key][0] += 1 if a.get("is_correct") else 0
        agg[key][1] += 1
        meta[key] = (sname, cname, tname)

    out = []
    for key, (c, t) in agg.items():
        acc = round(c / t * 100) if t else 0
        if acc < threshold:
            sname, cname, tname = meta[key]
            out.append(
                {
                    "key": key,
                    "subject": sname,
                    "chapter": cname,
                    "topic": tname,
                    "accuracy": acc,
                    "answered": t,
                }
            )
    out.sort(key=lambda x: x["accuracy"])
    return out


@router.get("/student/revision-topics")
def revision_topics(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """Weak topics a student should revise — their own weak areas, minus the ones
    they've already marked as revised."""
    _require_student(profile)
    service = get_service_client()
    weak = _flat_weak_topics(service, profile.tenant_id, profile.user_id)
    revised = select_all(
        service,
        "revised_topics",
        "topic_key, answered_at_revision",
        configure=lambda query: query.eq("student_id", profile.user_id).eq(
            "tenant_id", profile.tenant_id
        ),
        order_column="topic_key",
    )
    # A revised topic stays cleared until the student answers another question
    # in it. If it is still weak after new work, surface it again for revision.
    snapshots = {
        r["topic_key"]: int(r.get("answered_at_revision") or 0) for r in revised
    }
    return [
        w
        for w in weak
        if w["key"] not in snapshots or w["answered"] > snapshots[w["key"]]
    ]


class RevisedTopic(BaseModel):
    key: str


@router.post("/student/revision-topics/revised")
def mark_topic_revised(
    body: RevisedTopic, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    current = next(
        (
            topic
            for topic in _flat_weak_topics(
                service, profile.tenant_id, profile.user_id
            )
            if topic["key"] == body.key
        ),
        None,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Revision topic not found.")
    service.table("revised_topics").upsert(
        {
            "tenant_id": profile.tenant_id,
            "student_id": profile.user_id,
            "topic_key": body.key,
            "answered_at_revision": current["answered"],
        },
        on_conflict="student_id,topic_key",
    ).execute()
    return {"revised": body.key}


@router.get("/student/attempts", response_model=AttemptHistoryPage)
def student_attempts(
    profile: CurrentProfile = Depends(get_current_profile),
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    source: Literal["all", "quiz", "practice"] = "all",
    subject_id: str | None = None,
    chapter_id: str | None = None,
) -> AttemptHistoryPage:
    """The student's past (graded) attempts — quiz title, score, date — newest first."""
    _require_student(profile)
    page_size = bounded_page_size(page_size)
    page_cursor = decode_cursor(cursor)
    out = rpc_json_value(
        get_service_client(),
        "student_attempt_history_page",
        {
            "p_tenant": profile.tenant_id,
            "p_student": profile.user_id,
            "p_limit": page_size + 1,
            "p_before_at": page_cursor.occurred_at.isoformat() if page_cursor else None,
            "p_before_id": page_cursor.row_id if page_cursor else None,
            "p_source": source,
            "p_subject": subject_id,
            "p_chapter": chapter_id,
        },
        list,
    )
    has_more = len(out) > page_size
    items = out[:page_size]
    next_cursor = (
        encode_cursor(items[-1]["submitted_at"], items[-1]["attempt_id"])
        if has_more and items
        else None
    )
    for item in items:
        item.pop("_cursor_at", None)
    return AttemptHistoryPage(items=items, next_cursor=next_cursor)
