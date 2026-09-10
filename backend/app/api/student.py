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
from app.lib.api_errors import public_error
from app.lib.supabase import get_service_client
from app.services.events import ATTEMPT_SUBMITTED, log_event
from app.services.grading import grade_answer
from app.services.selector import enrolled_subject_ids

router = APIRouter(prefix="/api/v1", tags=["student"])


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only students can take quizzes.",
        )


QUESTION_ATTEMPT_COLUMNS = (
    "id, type, question_text, options, correct_answer, explanation, marks"
)


def _ordered_approved_questions(
    service, variant_id: str, tenant_id: str
) -> list[dict]:
    """The variant's APPROVED questions, in the teacher's chosen order."""
    links = (
        service.table("quiz_variant_questions")
        .select("question_id, order_index")
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
    return [by_id[link["question_id"]] for link in links if link["question_id"] in by_id]


def _approved_question_counts(
    service, variant_ids: list[str], tenant_id: str
) -> dict[str, int]:
    """Count approved linked questions for every variant in one round trip."""
    if not variant_ids:
        return {}
    links = (
        service.table("quiz_variant_questions")
        .select("variant_id, questions!inner(id)")
        .in_("variant_id", variant_ids)
        .eq("tenant_id", tenant_id)
        .eq("questions.review_status", "approved")
        .execute()
        .data
        or []
    )
    counts: dict[str, int] = {}
    for link in links:
        variant_id = link["variant_id"]
        counts[variant_id] = counts.get(variant_id, 0) + 1
    return counts


def _strip_answer(q: dict) -> dict:
    """What a student is allowed to SEE while taking — no correct_answer/why."""
    return {
        "id": q["id"],
        "type": q["type"],
        "question_text": q["question_text"],
        "options": q.get("options"),
        "marks": q.get("marks"),
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
        .select("id, title, published_at, subject_id, chapter_id")
        .eq("tenant_id", profile.tenant_id)
        .eq("status", "published")
        .in_("subject_id", subject_ids)
        .order("published_at", desc=True)
        .execute()
        .data
        or []
    )
    # Resolve subject + chapter NAMES so the student can browse by subject/chapter.
    subj_name = {
        s["id"]: s["name"]
        for s in (
            service.table("subjects")
            .select("id, name")
            .in_("id", subject_ids)
            .eq("tenant_id", profile.tenant_id)
            .execute()
            .data
            or []
        )
    }
    chapter_ids = list({s.get("chapter_id") for s in sets if s.get("chapter_id")})
    chap_name = {}
    if chapter_ids:
        chap_name = {
            c["id"]: c["name"]
            for c in (
                service.table("chapters")
                .select("id, name")
                .in_("id", chapter_ids)
                .eq("tenant_id", profile.tenant_id)
                .execute()
                .data
                or []
            )
        }
    # Fetch every variant and all approved-question counts in two catalog-sized
    # queries. This stays constant as the number of quiz sets/variants grows.
    set_variants: list[tuple[dict, list[dict]]] = []
    all_variant_ids: list[str] = []
    set_ids = [quiz_set["id"] for quiz_set in sets]
    variants = (
        service.table("quiz_variants")
        .select("id, quiz_set_id, variant_type, total_marks, time_limit_minutes")
        .in_("quiz_set_id", set_ids)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    counts = _approved_question_counts(
        service, [variant["id"] for variant in variants], profile.tenant_id
    )
    variants_by_set: dict[str, list[dict]] = {}
    for variant in variants:
        count = counts.get(variant["id"], 0)
        if count:
            variants_by_set.setdefault(variant["quiz_set_id"], []).append(
                {**variant, "question_count": count}
            )
            all_variant_ids.append(variant["id"])

    for quiz_set in sets:
        takeable = variants_by_set.get(quiz_set["id"], [])
        if takeable:
            set_variants.append((quiz_set, takeable))

    # This student's own attempts on those variants — so the UI can lead with the
    # quizzes they HAVEN'T attended yet, and show a best score on the ones they have.
    attempts_by_variant: dict[str, list[dict]] = {}
    if all_variant_ids:
        atts = (
            service.table("quiz_attempts")
            .select("variant_id, status, total_score")
            .eq("tenant_id", profile.tenant_id)
            .eq("student_id", profile.user_id)
            .in_("variant_id", all_variant_ids)
            .execute()
            .data
            or []
        )
        for a in atts:
            attempts_by_variant.setdefault(a["variant_id"], []).append(a)

    result = []
    for s, takeable in set_variants:
        annotated = []
        for v in takeable:
            graded = [
                a
                for a in attempts_by_variant.get(v["id"], [])
                if a["status"] == "graded"
            ]
            best_pct = None
            marks = v.get("total_marks")
            if graded and marks:
                top = max((a.get("total_score") or 0) for a in graded)
                best_pct = max(0, min(100, round(top / marks * 100)))
            annotated.append(
                {
                    **v,
                    "attempted": len(graded) > 0,
                    "attempt_count": len(graded),
                    "best_pct": best_pct,
                }
            )
        result.append(
            {
                **s,
                "subject_name": subj_name.get(s.get("subject_id")),
                "chapter_name": chap_name.get(s.get("chapter_id")),
                "variants": annotated,
            }
        )
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
        .select("status, subject_id")
        .eq("id", variant.data["quiz_set_id"])
        .eq("tenant_id", profile.tenant_id)
        .single()
        .execute()
    )
    if qs.data["status"] != "published":
        raise HTTPException(status_code=400, detail="This quiz is not published.")
    if qs.data.get("subject_id") not in enrolled_subject_ids(service, profile):
        raise HTTPException(
            status_code=403,
            detail="This quiz is not assigned to your course.",
        )

    questions = _ordered_approved_questions(
        service, body.variant_id, profile.tenant_id
    )
    if not questions:
        raise HTTPException(
            status_code=400,
            detail="This quiz does not have any approved questions yet.",
        )

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
    attempt_id = attempt.data[0]["id"]
    # These questions were already loaded to validate the quiz. Return the
    # answer-stripped taking state so the client can render immediately instead
    # of repeating the attempt + link + question queries after navigation.
    return {
        "attempt_id": attempt_id,
        "status": "in_progress",
        "questions": [_strip_answer(question) for question in questions],
        "autosave_state": {},
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


@router.get("/attempts/{attempt_id}")
def get_attempt(
    attempt_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_student(profile)
    service = get_service_client()
    attempt = _load_attempt(service, attempt_id, profile)
    questions = _ordered_approved_questions(
        service, attempt["variant_id"], profile.tenant_id
    )

    if attempt["status"] == "in_progress":
        return {
            "attempt_id": attempt_id,
            "status": "in_progress",
            "questions": [_strip_answer(q) for q in questions],
            "autosave_state": attempt.get("autosave_state") or {},
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


class AutosaveRequest(BaseModel):
    answers: dict[str, Any]


@router.patch("/attempts/{attempt_id}/autosave")
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
    allowed = {
        q["id"]
        for q in _ordered_approved_questions(
            service, attempt["variant_id"], profile.tenant_id
        )
    }
    answers = {key: value for key, value in body.answers.items() if key in allowed}
    service.table("quiz_attempts").update({"autosave_state": answers}).eq(
        "id", attempt_id
    ).eq("tenant_id", profile.tenant_id).eq(
        "student_id", profile.user_id
    ).execute()
    return {"saved": True}


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

    questions = _ordered_approved_questions(
        service, attempt["variant_id"], profile.tenant_id
    )
    submitted = {a.question_id: a.student_answer for a in body.answers}

    total = 0.0
    results = []
    answer_rows = []
    for q in questions:
        student_answer = submitted.get(q["id"])
        is_correct, awarded = grade_answer(q, student_answer)
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
                "student_answer": student_answer,
                "is_correct": is_correct,
                "marks_awarded": awarded,
            }
        )

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
    """Return every graded answer for one student across both quiz engines.

    Teacher-published quizzes use quiz_attempts/attempt_answers; Smart Quiz,
    Daily, Exam, Challenge and Revision use practice_sessions/practice_answers.
    Student analytics must combine both or the dashboard contradicts History.
    """
    quiz_attempts = (
        service.table("quiz_attempts")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("student_id", student_id)
        .eq("status", "graded")
        .execute()
        .data
        or []
    )
    practice_sessions = (
        service.table("practice_sessions")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("student_id", student_id)
        .eq("status", "graded")
        .execute()
        .data
        or []
    )

    answers: list[dict] = []
    attempt_ids = [row["id"] for row in quiz_attempts]
    if attempt_ids:
        answers.extend(
            service.table("attempt_answers")
            .select("question_id, is_correct")
            .in_("attempt_id", attempt_ids)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
    session_ids = [row["id"] for row in practice_sessions]
    if session_ids:
        answers.extend(
            service.table("practice_answers")
            .select("question_id, is_correct")
            .in_("session_id", session_ids)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
    return answers, len(quiz_attempts) + len(practice_sessions)


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
        qrows = (
            service.table("questions")
            .select("id, topic_id")
            .in_("id", qids)
            .eq("tenant_id", tid)
            .execute()
            .data
            or []
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
            names = (
                service.table("topics")
                .select("id, name")
                .in_("id", list(agg.keys()))
                .eq("tenant_id", tid)
                .execute()
                .data
                or []
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
        "weak_areas": topic_accuracy[:3],
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
    qrows = (
        service.table("questions")
        .select("id, chapter_id, topic_id")
        .in_("id", qids)
        .eq("tenant_id", tid)
        .execute()
        .data
        or []
    )
    qmap = {q["id"]: q for q in qrows}

    chapter_ids = list({q["chapter_id"] for q in qrows if q.get("chapter_id")})
    chapters = (
        service.table("chapters").select("id, name, subject_id").in_("id", chapter_ids).eq("tenant_id", tid).execute().data
        if chapter_ids
        else []
    ) or []
    chmap = {c["id"]: c for c in chapters}
    subject_ids = list({c["subject_id"] for c in chapters})
    subjects = (
        {
            s["id"]: s["name"]
            for s in (
                service.table("subjects").select("id, name").in_("id", subject_ids).eq("tenant_id", tid).execute().data
                or []
            )
        }
        if subject_ids
        else {}
    )
    topic_ids = list({q["topic_id"] for q in qrows if q.get("topic_id")})
    topics = (
        {
            t["id"]: t["name"]
            for t in (
                service.table("topics").select("id, name").in_("id", topic_ids).eq("tenant_id", tid).execute().data
                or []
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

    Each item: {key, subject, chapter, topic, accuracy, answered}. `key` is a
    stable "Subject||Chapter||Topic" string used to mark a topic as revised.
    """
    from collections import defaultdict

    answers, _ = _student_graded_answers(service, tid, uid)
    if not answers:
        return []
    qids = list({a["question_id"] for a in answers})
    qrows = (
        service.table("questions")
        .select("id, chapter_id, topic_id")
        .in_("id", qids)
        .eq("tenant_id", tid)
        .execute()
        .data
        or []
    )
    qmap = {q["id"]: q for q in qrows}
    chapter_ids = list({q["chapter_id"] for q in qrows if q.get("chapter_id")})
    chapters = (
        service.table("chapters").select("id, name, subject_id").in_("id", chapter_ids).eq("tenant_id", tid).execute().data
        if chapter_ids
        else []
    ) or []
    chmap = {c["id"]: c for c in chapters}
    subject_ids = list({c["subject_id"] for c in chapters})
    subjects = (
        {
            s["id"]: s["name"]
            for s in (
                service.table("subjects").select("id, name").in_("id", subject_ids).eq("tenant_id", tid).execute().data
                or []
            )
        }
        if subject_ids
        else {}
    )
    topic_ids = list({q["topic_id"] for q in qrows if q.get("topic_id")})
    topics = (
        {
            t["id"]: t["name"]
            for t in (
                service.table("topics").select("id, name").in_("id", topic_ids).eq("tenant_id", tid).execute().data
                or []
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
        key = f"{sname}||{cname}||{tname}"
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
    revised = (
        service.table("revised_topics")
        .select("topic_key")
        .eq("student_id", profile.user_id)
        .eq("tenant_id", profile.tenant_id)
        .execute()
        .data
        or []
    )
    done = {r["topic_key"] for r in revised}
    return [w for w in weak if w["key"] not in done]


class RevisedTopic(BaseModel):
    key: str


@router.post("/student/revision-topics/revised")
def mark_topic_revised(
    body: RevisedTopic, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_student(profile)
    service = get_service_client()
    service.table("revised_topics").upsert(
        {
            "tenant_id": profile.tenant_id,
            "student_id": profile.user_id,
            "topic_key": body.key,
        },
        on_conflict="student_id,topic_key",
    ).execute()
    return {"revised": body.key}


@router.get("/student/attempts")
def student_attempts(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[dict]:
    """The student's past (graded) attempts — quiz title, score, date — newest first."""
    _require_student(profile)
    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id

    attempts = (
        service.table("quiz_attempts")
        .select("id, variant_id, total_score, submitted_at")
        .eq("tenant_id", tid)
        .eq("student_id", uid)
        .eq("status", "graded")
        .order("submitted_at", desc=True)
        .execute()
        .data
        or []
    )
    variant_ids = list({a["variant_id"] for a in attempts})
    vrows = []
    if variant_ids:
        vrows = (
            service.table("quiz_variants")
            .select("id, variant_type, total_marks, quiz_set_id")
            .in_("id", variant_ids)
            .eq("tenant_id", tid)
            .execute()
            .data
            or []
        )
    variants = {v["id"]: v for v in vrows}

    set_ids = list({v["quiz_set_id"] for v in variants.values()})
    titles: dict[str, str] = {}
    if set_ids:
        srows = (
            service.table("quiz_sets")
            .select("id, title")
            .in_("id", set_ids)
            .eq("tenant_id", tid)
            .execute()
            .data
            or []
        )
        titles = {s["id"]: s["title"] for s in srows}

    out = []
    for a in attempts:
        v = variants.get(a["variant_id"], {})
        out.append(
            {
                "attempt_id": a["id"],
                "quiz_title": titles.get(v.get("quiz_set_id"), "Quiz"),
                "variant_type": v.get("variant_type"),
                "total_score": a.get("total_score"),
                "max_score": v.get("total_marks"),
                "submitted_at": a.get("submitted_at"),
                "source": "quiz",
            }
        )

    practice = (
        service.table("practice_sessions")
        .select("id, mode, total_score, max_score, submitted_at")
        .eq("tenant_id", tid)
        .eq("student_id", uid)
        .eq("status", "graded")
        .execute()
        .data
        or []
    )
    for session in practice:
        mode = str(session.get("mode") or "practice").replace("_", " ").title()
        out.append(
            {
                "attempt_id": session["id"],
                "quiz_title": f"{mode} practice",
                "variant_type": session.get("mode"),
                "total_score": session.get("total_score"),
                "max_score": session.get("max_score"),
                "submitted_at": session.get("submitted_at"),
                "source": "practice",
            }
        )
    return sorted(out, key=lambda row: row.get("submitted_at") or "", reverse=True)
