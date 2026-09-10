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
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.supabase import get_service_client
from app.services.grading import grade_answer
from app.services.selector import select_question_ids
from app.services.student_access import student_has_graded_question

router = APIRouter(prefix="/api/v1", tags=["practice"])


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can practise.",
        )


def _exam_deadline_passed(session: dict, now: datetime | None = None) -> bool:
    config = session.get("config") or {}
    if session.get("mode") != "exam" or not config.get("duration_minutes"):
        return False
    if not session.get("started_at"):
        return False
    started = datetime.fromisoformat(str(session["started_at"]).replace("Z", "+00:00"))
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    deadline = started + timedelta(
        minutes=float(config["duration_minutes"]), seconds=10
    )
    return (now or datetime.now(timezone.utc)) > deadline


# Sensible default exam pattern; a per-institution value in tenants.exam_config
# overrides any of these keys.
DEFAULT_EXAM = {"questions": 50, "duration_minutes": 60, "negative_marking": 0.25}
PRACTICE_QUESTION_COLUMNS = (
    "id, type, question_text, options, correct_answer, explanation, marks"
)


def _exam_config(service, tenant_id: str) -> dict:
    """This institution's exam pattern, falling back to the app default."""
    row = (
        service.table("tenants")
        .select("exam_config")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    cfg = (row.data or {}).get("exam_config") if row and row.data else None
    return {**DEFAULT_EXAM, **(cfg or {})}


def _answered(v: Any) -> bool:
    """Did the student actually answer? (blank ≠ wrong, so no negative mark.)"""
    if v is None or v == "":
        return False
    if isinstance(v, list):
        return len(v) > 0
    return True


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
        .select(PRACTICE_QUESTION_COLUMNS)
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
        .eq("tenant_id", session["tenant_id"])
        .maybe_single()
        .execute()
    )
    return ch.data["share_token"] if ch and ch.data else None


# ── Start / take / submit a practice session ─────────────────────────────────
class StartPractice(BaseModel):
    # Daily, exam and challenge sessions have dedicated endpoints with extra
    # invariants. The generic endpoint must not let a client bypass those rules.
    mode: Literal["smart", "chapter", "revision"] = "smart"
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
    # Prime the first render with the questions selected above. This replaces
    # the immediate GET that otherwise reloads the new session and its questions.
    questions = _load_questions(service, ids, profile.tenant_id)
    return {
        "session_id": row["id"],
        "attempt_id": row["id"],
        "status": "in_progress",
        "questions": [_strip(question) for question in questions],
        "autosave_state": {},
    }


@router.get("/practice/sessions/{session_id}")
def get_practice(
    session_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    s = _load_session(service, session_id, profile)
    questions = _load_questions(service, s["question_ids"], profile.tenant_id)

    if s["status"] == "in_progress":
        cfg = s.get("config") or {}
        return {
            "attempt_id": session_id,
            "status": "in_progress",
            "questions": [_strip(q) for q in questions],
            "autosave_state": s.get("autosave_state") or {},
            # Present only for timed modes (exam) — drives the countdown + auto-submit.
            "time_limit_minutes": cfg.get("duration_minutes"),
            "started_at": s.get("started_at"),
        }

    answers = (
        service.table("practice_answers")
        .select("*")
        .eq("session_id", session_id)
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


class AutosavePractice(BaseModel):
    answers: dict[str, Any]


@router.patch("/practice/sessions/{session_id}/autosave")
def autosave_practice(
    session_id: str,
    body: AutosavePractice,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    session = _load_session(service, session_id, profile)
    if session["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="This session is already submitted.")
    if _exam_deadline_passed(session):
        raise HTTPException(status_code=400, detail="This exam has ended.")
    allowed = set(session.get("question_ids") or [])
    answers = {key: value for key, value in body.answers.items() if key in allowed}
    service.table("practice_sessions").update({"autosave_state": answers}).eq(
        "id", session_id
    ).eq("tenant_id", profile.tenant_id).eq(
        "student_id", profile.user_id
    ).execute()
    return {"saved": True}


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
    cfg = s.get("config") or {}
    if _exam_deadline_passed(s):
        # A modified client cannot add answers after the exam expires. Preserve
        # the last server-side autosave so a slow final request does not erase
        # work that was saved before the deadline.
        submitted = dict(s.get("autosave_state") or {})
    # Negative marking is frozen into the session's config (exam mode). A wrong,
    # ANSWERED question loses marks; a blank one scores 0 (never negative).
    neg = float(cfg.get("negative_marking") or 0)

    total = 0.0
    max_score = 0.0
    results = []
    answer_rows = []
    for q in questions:
        student_answer = submitted.get(q["id"])
        is_correct, awarded = grade_answer(q, student_answer)
        if not is_correct and neg > 0 and _answered(student_answer):
            awarded = -neg
        total += awarded
        max_score += float(q.get("marks") or 1)
        answer_rows.append(
            {
                "tenant_id": profile.tenant_id,
                "session_id": session_id,
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
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        )

    if neg > 0:
        total = max(0.0, total)  # an exam total never drops below zero

    claimed = (
        service.table("practice_sessions")
        .update(
            {
                "status": "graded",
                "total_score": total,
                "max_score": max_score,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "autosave_state": {},
            }
        )
        .eq("id", session_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .eq("status", "in_progress")
        .execute()
    )
    if not claimed.data:
        raise HTTPException(status_code=400, detail="This session is already submitted.")
    try:
        if answer_rows:
            service.table("practice_answers").upsert(
                answer_rows, on_conflict="session_id,question_id"
            ).execute()
    except Exception as exc:  # noqa: BLE001
        service.table("practice_answers").delete().eq("session_id", session_id).eq(
            "tenant_id", profile.tenant_id
        ).execute()
        service.table("practice_sessions").update(
            {
                "status": "in_progress",
                "total_score": None,
                "max_score": None,
                "submitted_at": None,
            }
        ).eq("id", session_id).eq("tenant_id", profile.tenant_id).eq(
            "student_id", profile.user_id
        ).execute()
        raise public_error(
            500,
            "We couldn't save your answers. Your practice session is still open; please try again.",
            operation="save submitted practice answers",
            exception=exc,
        ) from exc

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
    # Revision reveals the answer, so only questions this student has already
    # submitted may be bookmarked. This also blocks probing another course's
    # approved question ids within the same institution.
    qrow = (
        service.table("questions")
        .select("id")
        .eq("id", body.question_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("review_status", "approved")
        .maybe_single()
        .execute()
    )
    if (
        qrow is None
        or not qrow.data
        or not student_has_graded_question(service, body.question_id, profile)
    ):
        raise HTTPException(status_code=404, detail="Question not found.")
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


# ── Exam Simulator (timed, negative marking, per-institution pattern) ─────────
@router.get("/exam/config")
def exam_config(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """The institution's exam pattern — for the pre-exam briefing screen."""
    _require_student(profile)
    service = get_service_client()
    cfg = _exam_config(service, profile.tenant_id)
    return {
        "questions": int(cfg["questions"]),
        "duration_minutes": int(cfg["duration_minutes"]),
        "negative_marking": float(cfg["negative_marking"]),
    }


@router.post("/exam/start")
def start_exam(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """Begin a full, timed exam. The pattern (count, duration, negative marking)
    is frozen into the session so mid-exam config changes can't affect it."""
    _require_student(profile)
    service = get_service_client()
    cfg = _exam_config(service, profile.tenant_id)
    ids = select_question_ids(
        service, profile, mode="exam", count=int(cfg["questions"])
    )
    if not ids:
        raise HTTPException(
            status_code=400,
            detail="Not enough approved questions to run an exam yet.",
        )
    sess = (
        service.table("practice_sessions")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "student_id": profile.user_id,
                "mode": "exam",
                "config": {
                    "count": len(ids),
                    "negative_marking": float(cfg["negative_marking"]),
                    "duration_minutes": int(cfg["duration_minutes"]),
                },
                "question_ids": ids,
                "status": "in_progress",
            }
        )
        .execute()
        .data[0]
    )
    return {
        "session_id": sess["id"],
        "questions": len(ids),
        "duration_minutes": int(cfg["duration_minutes"]),
    }


# ── Leaderboard (course-scoped, within the institution) ──────────────────────
@router.get("/leaderboard")
def leaderboard(
    course_id: str | None = None,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Rank students in the SAME COURSE as the caller — a college has many
    departments/courses, so a global ranking would mix unrelated students. Ranked
    by total marks earned across all graded work, with accuracy. Also returns the
    caller's course list so the UI can switch between courses."""
    _require_student(profile)
    from collections import defaultdict

    service = get_service_client()
    t = profile.tenant_id

    # Which courses is the caller in? Default to the first; honour ?course_id=.
    my_course_ids = list(
        {
            e["course_id"]
            for e in (
                service.table("enrollments")
                .select("course_id")
                .eq("profile_id", profile.user_id)
                .eq("tenant_id", t)
                .execute()
                .data
                or []
            )
        }
    )
    empty = {
        "course_id": None,
        "course_name": None,
        "courses": [],
        "top": [],
        "me": None,
        "total": 0,
    }
    if not my_course_ids:
        return empty
    courses = (
        service.table("courses")
        .select("id, name")
        .in_("id", my_course_ids)
        .eq("tenant_id", t)
        .order("name")
        .execute()
        .data
        or []
    )
    if not courses:
        return empty
    valid = {c["id"]: c["name"] for c in courses}
    selected = course_id if course_id in valid else courses[0]["id"]
    base = {
        "course_id": selected,
        "course_name": valid[selected],
        "courses": [{"id": c["id"], "name": c["name"]} for c in courses],
    }

    # Everyone enrolled in the selected course (teachers are filtered out later).
    course_students = list(
        {
            e["profile_id"]
            for e in (
                service.table("enrollments")
                .select("profile_id")
                .eq("course_id", selected)
                .eq("tenant_id", t)
                .execute()
                .data
                or []
            )
        }
    )
    if not course_students:
        return {**base, "top": [], "me": None, "total": 0}

    # Restrict teacher-quiz attempts to quiz sets whose subject belongs to the
    # selected course. Previously every attempt by an enrolled student counted,
    # including work completed for a different course.
    course_subjects = {
        row["id"]
        for row in (
            service.table("subjects")
            .select("id")
            .eq("course_id", selected)
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        )
    }
    attempts = (
        service.table("quiz_attempts")
        .select("id, student_id, total_score, variant_id")
        .eq("tenant_id", t)
        .eq("status", "graded")
        .in_("student_id", course_students)
        .execute()
        .data
        or []
    )
    variant_ids = list({a["variant_id"] for a in attempts if a.get("variant_id")})
    variants: dict = {}
    if variant_ids:
        for v in (
            service.table("quiz_variants")
            .select("id, total_marks, quiz_set_id")
            .in_("id", variant_ids)
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            variants[v["id"]] = v
    set_ids = list({v["quiz_set_id"] for v in variants.values()})
    set_subject: dict[str, str | None] = {}
    if set_ids:
        for quiz_set in (
            service.table("quiz_sets")
            .select("id, subject_id")
            .in_("id", set_ids)
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            set_subject[quiz_set["id"]] = quiz_set.get("subject_id")
    attempts = [
        attempt
        for attempt in attempts
        if (
            (variant := variants.get(attempt.get("variant_id")))
            and set_subject.get(variant["quiz_set_id"]) in course_subjects
        )
    ]

    sessions = (
        service.table("practice_sessions")
        .select("id, student_id, total_score, max_score, subject_id, chapter_id")
        .eq("tenant_id", t)
        .eq("status", "graded")
        .in_("student_id", course_students)
        .execute()
        .data
        or []
    )

    # Subject-scoped practice belongs to that subject's course. An unscoped
    # session can only be attributed safely when the student has one course;
    # otherwise counting it on every course would duplicate and contaminate ranks.
    chapter_ids = list({s["chapter_id"] for s in sessions if s.get("chapter_id")})
    chapter_subject: dict[str, str] = {}
    if chapter_ids:
        for chapter in (
            service.table("chapters")
            .select("id, subject_id")
            .in_("id", chapter_ids)
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            chapter_subject[chapter["id"]] = chapter["subject_id"]
    enrolment_rows = (
        service.table("enrollments")
        .select("profile_id, course_id")
        .in_("profile_id", course_students)
        .eq("tenant_id", t)
        .execute()
        .data
        or []
    )
    student_courses: dict[str, set[str]] = defaultdict(set)
    for enrolment in enrolment_rows:
        student_courses[enrolment["profile_id"]].add(enrolment["course_id"])

    def session_belongs_to_course(session: dict) -> bool:
        subject_id = session.get("subject_id") or chapter_subject.get(
            session.get("chapter_id")
        )
        if subject_id:
            return subject_id in course_subjects
        return student_courses.get(session["student_id"], set()) == {selected}

    sessions = [s for s in sessions if session_belongs_to_course(s)]

    agg: dict = defaultdict(
        lambda: {"points": 0.0, "max": 0.0, "n": 0, "correct": 0, "answered": 0}
    )
    for a in attempts:
        d = agg[a["student_id"]]
        d["points"] += float(a.get("total_score") or 0)
        d["max"] += float(variants.get(a["variant_id"], {}).get("total_marks") or 0)
        d["n"] += 1
    for s in sessions:
        d = agg[s["student_id"]]
        d["points"] += float(s.get("total_score") or 0)
        d["max"] += float(s.get("max_score") or 0)
        d["n"] += 1

    # Accuracy means correct answers / answered questions. Score percentage is
    # not equivalent when an exam applies negative marking or variable marks.
    attempt_owner = {a["id"]: a["student_id"] for a in attempts}
    if attempt_owner:
        for answer in (
            service.table("attempt_answers")
            .select("attempt_id, is_correct")
            .in_("attempt_id", list(attempt_owner))
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            d = agg[attempt_owner[answer["attempt_id"]]]
            d["answered"] += 1
            d["correct"] += 1 if answer.get("is_correct") else 0
    session_owner = {s["id"]: s["student_id"] for s in sessions}
    if session_owner:
        for answer in (
            service.table("practice_answers")
            .select("session_id, is_correct")
            .in_("session_id", list(session_owner))
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            d = agg[session_owner[answer["session_id"]]]
            d["answered"] += 1
            d["correct"] += 1 if answer.get("is_correct") else 0

    # Names — and this also filters to actual students (not staff test accounts).
    names: dict = {}
    if agg:
        for p in (
            service.table("profiles")
            .select("id, full_name, role")
            .in_("id", list(agg.keys()))
            .eq("tenant_id", t)
            .execute()
            .data
            or []
        ):
            if p.get("role") == "student":
                names[p["id"]] = p.get("full_name") or "Student"

    rows = []
    for sid, d in agg.items():
        if sid not in names:
            continue
        rows.append(
            {
                "student_id": sid,
                "name": names[sid],
                "points": round(d["points"], 2),
                "accuracy": (
                    round(d["correct"] / d["answered"] * 100)
                    if d["answered"]
                    else 0
                ),
                "quizzes": d["n"],
            }
        )
    rows.sort(key=lambda r: (-r["points"], -r["accuracy"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["is_you"] = r["student_id"] == profile.user_id

    def _clean(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "student_id"}

    me = next((r for r in rows if r["is_you"]), None)
    return {
        **base,
        "top": [_clean(r) for r in rows[:20]],
        "me": _clean(me) if me else None,
        "total": len(rows),
    }
