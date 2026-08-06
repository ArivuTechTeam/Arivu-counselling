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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.grading import grade_answer

router = APIRouter(prefix="/api/v1", tags=["student"])


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can take quizzes.",
        )


def _ordered_approved_questions(service, variant_id: str) -> list[dict]:
    """The variant's APPROVED questions, in the teacher's chosen order."""
    links = (
        service.table("quiz_variant_questions")
        .select("question_id, order_index")
        .eq("variant_id", variant_id)
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
        .select("*")
        .in_("id", ids)
        .eq("review_status", "approved")
        .execute()
        .data
        or []
    )
    by_id = {row["id"]: row for row in rows}
    return [by_id[link["question_id"]] for link in links if link["question_id"] in by_id]


def _strip_answer(q: dict) -> dict:
    """What a student is allowed to SEE while taking — no correct_answer/why."""
    return {
        "id": q["id"],
        "type": q["type"],
        "question_text": q["question_text"],
        "options": q.get("options"),
        "marks": q.get("marks"),
    }


@router.get("/quizzes")
def list_quizzes(profile: CurrentProfile = Depends(get_current_profile)) -> list[dict]:
    _require_student(profile)
    service = get_service_client()

    # 1) Which courses is this student enrolled in?
    enrollments = (
        service.table("enrollments")
        .select("course_id")
        .eq("profile_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    course_ids = [e["course_id"] for e in enrollments]
    if not course_ids:
        return []  # not enrolled in anything -> no quizzes

    # 2) Which subjects belong to those courses?
    subjects = (
        service.table("subjects")
        .select("id")
        .in_("course_id", course_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    subject_ids = [s["id"] for s in subjects]
    if not subject_ids:
        return []

    # 3) Published quizzes tagged with one of those subjects.
    sets = (
        service.table("quiz_sets")
        .select("id, title, published_at, subject_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("status", "published")
        .in_("subject_id", subject_ids)
        .order("published_at", desc=True)
        .execute()
        .data
        or []
    )
    result = []
    for s in sets:
        variants = (
            service.table("quiz_variants")
            .select("id, variant_type, total_marks, time_limit_minutes")
            .eq("quiz_set_id", s["id"])
            .execute()
            .data
            or []
        )
        takeable = []
        for v in variants:
            count = len(_ordered_approved_questions(service, v["id"]))
            if count > 0:  # only offer variants that actually have questions
                takeable.append({**v, "question_count": count})
        if takeable:
            result.append({**s, "variants": takeable})
    return result


class StartAttemptRequest(BaseModel):
    variant_id: str


@router.post("/attempts")
def start_attempt(
    body: StartAttemptRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()

    variant = (
        service.table("quiz_variants")
        .select("id, quiz_set_id")
        .eq("id", body.variant_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if variant is None or not variant.data:
        raise HTTPException(status_code=404, detail="Quiz variant not found.")

    qs = (
        service.table("quiz_sets")
        .select("status")
        .eq("id", variant.data["quiz_set_id"])
        .single()
        .execute()
    )
    if qs.data["status"] != "published":
        raise HTTPException(status_code=400, detail="This quiz is not published.")

    attempt = (
        service.table("quiz_attempts")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "variant_id": body.variant_id,
                "student_id": profile.user_id,
                "status": "in_progress",
            }
        )
        .execute()
    )
    return {"attempt_id": attempt.data[0]["id"]}


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


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt = _load_attempt(service, attempt_id, profile)
    questions = _ordered_approved_questions(service, attempt["variant_id"])

    if attempt["status"] == "in_progress":
        return {
            "attempt_id": attempt_id,
            "status": "in_progress",
            "questions": [_strip_answer(q) for q in questions],
        }

    # Graded: return full results (answers now allowed).
    answers = (
        service.table("attempt_answers")
        .select("*")
        .eq("attempt_id", attempt_id)
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
                "student_answer": a.get("student_answer"),
                "is_correct": a.get("is_correct"),
                "marks_awarded": a.get("marks_awarded"),
            }
        )
    max_score = sum(float(q.get("marks") or 1) for q in questions)
    return {
        "attempt_id": attempt_id,
        "status": attempt["status"],
        "total_score": attempt["total_score"],
        "max_score": max_score,
        "results": results,
    }


class SubmittedAnswer(BaseModel):
    question_id: str
    student_answer: Any = None


class SubmitRequest(BaseModel):
    answers: list[SubmittedAnswer]


@router.post("/attempts/{attempt_id}/submit")
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

    questions = _ordered_approved_questions(service, attempt["variant_id"])
    submitted = {a.question_id: a.student_answer for a in body.answers}

    total = 0.0
    results = []
    for q in questions:
        student_answer = submitted.get(q["id"])
        is_correct, awarded = grade_answer(q, student_answer)
        total += awarded
        service.table("attempt_answers").insert(
            {
                "tenant_id": profile.tenant_id,
                "attempt_id": attempt_id,
                "question_id": q["id"],
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        ).execute()
        results.append(
            {
                "id": q["id"],
                "type": q["type"],
                "question_text": q["question_text"],
                "options": q.get("options"),
                "correct_answer": q["correct_answer"],
                "explanation": q.get("explanation"),
                "marks": q.get("marks"),
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        )

    service.table("quiz_attempts").update(
        {
            "status": "graded",
            "total_score": total,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", attempt_id).execute()

    max_score = sum(float(q.get("marks") or 1) for q in questions)
    return {
        "attempt_id": attempt_id,
        "status": "graded",
        "total_score": total,
        "max_score": max_score,
        "results": results,
    }
