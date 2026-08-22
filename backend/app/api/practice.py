"""
Self-serve practice — the student-initiated counterpart to teacher quizzes.

One engine, many modes: a practice_session is a FROZEN set of question ids +
config, taken by one student and graded by the shared grading service. Smart
Quiz, chapter practice, exam simulator, daily challenge, challenge-a-friend and
revision all ride on this.

Session endpoints return the SAME JSON shape as /attempts (attempt_id, status,
questions|results) so the existing take/results UI is reused, not duplicated.
Also hosts the revision-list bookmark endpoints.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.services.grading import grade_answer
from app.services.selector import select_question_ids

router = APIRouter(prefix="/api/v1", tags=["practice"])


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can practise.",
        )


def _strip(q: dict) -> dict:
    """What a student may SEE while taking — no correct_answer/explanation."""
    return {
        "id": q["id"],
        "type": q["type"],
        "question_text": q["question_text"],
        "options": q.get("options"),
        "marks": q.get("marks"),
    }


def _load_questions(service, ids: list[str], tenant_id: str) -> list[dict]:
    """Load questions by id, preserving the session's FROZEN order."""
    if not ids:
        return []
    rows = (
        service.table("questions")
        .select("*")
        .in_("id", ids)
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _load_session(service, session_id: str, profile: CurrentProfile) -> dict:
    s = (
        service.table("practice_sessions")
        .select("*")
        .eq("id", session_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)  # a student only sees their own
        .maybe_single()
        .execute()
    )
    if s is None or not s.data:
        raise HTTPException(status_code=404, detail="Practice session not found.")
    return s.data


def _challenge_token(service, session: dict) -> str | None:
    """If this session belongs to a challenge, its share token (for the UI link)."""
    cid = session.get("challenge_id")
    if not cid:
        return None
    ch = (
        service.table("challenges")
        .select("share_token")
        .eq("id", cid)
        .maybe_single()
        .execute()
    )
    return ch.data["share_token"] if ch and ch.data else None


# ── Start / take / submit a practice session ─────────────────────────────────
class StartPractice(BaseModel):
    mode: str = "smart"
    subject_id: str | None = None
    chapter_id: str | None = None
    count: int = 15
    difficulty: str | None = None


@router.post("/practice/sessions")
def start_practice(
    body: StartPractice, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    ids = select_question_ids(
        service,
        profile,
        mode=body.mode,
        subject_id=body.subject_id,
        chapter_id=body.chapter_id,
        count=body.count,
        difficulty=body.difficulty,
    )
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="No questions available yet for this selection — ask your "
            "teacher to publish some, or try another subject.",
        )
    row = (
        service.table("practice_sessions")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "mode": body.mode,
                "subject_id": body.subject_id,
                "chapter_id": body.chapter_id,
                "config": {"count": len(ids), "difficulty": body.difficulty},
                "question_ids": ids,
                "status": "in_progress",
            }
        )
        .execute()
        .data[0]
    )
    return {"session_id": row["id"]}


@router.get("/practice/sessions/{session_id}")
def get_practice(
    session_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    s = _load_session(service, session_id, profile)
    questions = _load_questions(service, s["question_ids"], profile.tenant_id)

    if s["status"] == "in_progress":
        return {
            "attempt_id": session_id,
            "status": "in_progress",
            "questions": [_strip(q) for q in questions],
        }

    answers = (
        service.table("practice_answers")
        .select("*")
        .eq("session_id", session_id)
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
    return {
        "attempt_id": session_id,
        "status": "graded",
        "quiz_title": f"{s['mode'].replace('_', ' ').title()} practice",
        "total_score": s["total_score"],
        "max_score": s["max_score"],
        "challenge_token": _challenge_token(service, s),
        "results": results,
    }


class SubmittedAnswer(BaseModel):
    question_id: str
    student_answer: Any = None


class SubmitPractice(BaseModel):
    answers: list[SubmittedAnswer]


@router.post("/practice/sessions/{session_id}/submit")
def submit_practice(
    session_id: str,
    body: SubmitPractice,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    s = _load_session(service, session_id, profile)
    if s["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="This session is already submitted.")

    questions = _load_questions(service, s["question_ids"], profile.tenant_id)
    submitted = {a.question_id: a.student_answer for a in body.answers}

    total = 0.0
    max_score = 0.0
    results = []
    for q in questions:
        student_answer = submitted.get(q["id"])
        is_correct, awarded = grade_answer(q, student_answer)
        total += awarded
        max_score += float(q.get("marks") or 1)
        service.table("practice_answers").insert(
            {
                "tenant_id": profile.tenant_id,
                "session_id": session_id,
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

    service.table("practice_sessions").update(
        {
            "status": "graded",
            "total_score": total,
            "max_score": max_score,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", session_id).execute()

    return {
        "attempt_id": session_id,
        "status": "graded",
        "quiz_title": f"{s['mode'].replace('_', ' ').title()} practice",
        "total_score": total,
        "max_score": max_score,
        "challenge_token": _challenge_token(service, s),
        "results": results,
    }


# ── Revision list (bookmarks) ────────────────────────────────────────────────
class BookmarkRequest(BaseModel):
    question_id: str


@router.get("/bookmarks")
def list_bookmarks(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """The student's bookmarked questions, with answers/explanations to revise."""
    _require_student(profile)
    service = get_service_client()
    marks = (
        service.table("bookmarks")
        .select("question_id, created_at")
        .eq("student_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    ids = [m["question_id"] for m in marks]
    if not ids:
        return []
    qrows = (
        service.table("questions")
        .select("id, type, question_text, options, correct_answer, explanation, difficulty")
        .in_("id", ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    by_id = {q["id"]: q for q in qrows}
    return [by_id[i] for i in ids if i in by_id]  # newest-first order preserved


@router.post("/bookmarks")
def add_bookmark(
    body: BookmarkRequest, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    # Idempotent: unique(student_id, question_id) means re-adding is a no-op.
    service.table("bookmarks").upsert(
        {
            "tenant_id": profile.tenant_id,
            "student_id": profile.user_id,
            "question_id": body.question_id,
        },
        on_conflict="student_id,question_id",
    ).execute()
    return {"bookmarked": body.question_id}


@router.delete("/bookmarks/{question_id}")
def remove_bookmark(
    question_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    service.table("bookmarks").delete().eq("student_id", profile.user_id).eq(
        "question_id", question_id
    ).eq("tenant_id", profile.tenant_id).execute()
    return {"removed": question_id}


# ── Daily Challenge (one per day + streak) ───────────────────────────────────
def _daily_sessions(service, profile: CurrentProfile) -> list[dict]:
    return (
        service.table("practice_sessions")
        .select("id, status, started_at, submitted_at")
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("mode", "daily")
        .execute()
        .data
        or []
    )


def _streak(done_dates: set[str], today: date) -> tuple[int, int]:
    """(current, longest) streak of consecutive completed days.

    The current streak is alive if today OR yesterday was completed.
    """
    def run_ending(day: date) -> int:
        n, cur = 0, day
        while cur.isoformat() in done_dates:
            n += 1
            cur -= timedelta(days=1)
        return n

    if today.isoformat() in done_dates:
        current = run_ending(today)
    elif (today - timedelta(days=1)).isoformat() in done_dates:
        current = run_ending(today - timedelta(days=1))
    else:
        current = 0

    longest = 0
    for d in done_dates:
        day = date.fromisoformat(d)
        if (day - timedelta(days=1)).isoformat() not in done_dates:  # run start
            n, cur = 0, day
            while cur.isoformat() in done_dates:
                n += 1
                cur += timedelta(days=1)
            longest = max(longest, n)
    return current, longest


@router.get("/daily")
def get_daily(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """Today's challenge status + the student's streak (last 7 days strip)."""
    _require_student(profile)
    service = get_service_client()
    sessions = _daily_sessions(service, profile)
    today = date.today()
    today_iso = today.isoformat()

    done_dates = {
        (s["submitted_at"] or "")[:10]
        for s in sessions
        if s["status"] == "graded" and s.get("submitted_at")
    }
    done_dates.discard("")
    done_today = today_iso in done_dates

    today_session_id = None
    for s in sessions:
        if s["status"] == "in_progress" and (s.get("started_at") or "")[:10] == today_iso:
            today_session_id = s["id"]
            break

    current, longest = _streak(done_dates, today)
    last7 = [
        {
            "date": (today - timedelta(days=i)).isoformat(),
            "done": (today - timedelta(days=i)).isoformat() in done_dates,
        }
        for i in range(6, -1, -1)
    ]
    return {
        "done_today": done_today,
        "streak": current,
        "longest": longest,
        "today_session_id": today_session_id,
        "last7": last7,
    }


@router.post("/daily/start")
def start_daily(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """Start (or resume) today's daily challenge — one per day."""
    _require_student(profile)
    service = get_service_client()
    sessions = _daily_sessions(service, profile)
    today_iso = date.today().isoformat()

    for s in sessions:  # resume an unfinished one from today
        if s["status"] == "in_progress" and (s.get("started_at") or "")[:10] == today_iso:
            return {"session_id": s["id"]}
    for s in sessions:  # already completed today
        if s["status"] == "graded" and (s.get("submitted_at") or "")[:10] == today_iso:
            raise HTTPException(
                status_code=400,
                detail="You've already done today's challenge — come back tomorrow!",
            )

    ids = select_question_ids(service, profile, mode="daily", count=10)
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="No questions available for today's challenge yet.",
        )
    sess = (
        service.table("practice_sessions")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "mode": "daily",
                "config": {"count": len(ids)},
                "question_ids": ids,
                "status": "in_progress",
            }
        )
        .execute()
        .data[0]
    )
    return {"session_id": sess["id"]}
