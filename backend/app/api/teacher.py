"""
Teacher class analytics (read-only) for the Class overview.

  GET /api/v1/teacher/class-overview
    Aggregates real attempt data on the teacher's own quiz sets into:
      - class_accuracy (overall %)
      - accuracy_by_quiz  (per quiz: avg accuracy + attempts)
      - needs_attention   (students scoring low, lowest first)
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.pagination import DEFAULT_PAGE_SIZE, bounded_page_size, decode_cursor, encode_cursor
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import rpc_json_value, select_all, select_all_in
from app.services.attempt_timing import is_answered
from app.services.teacher_access import teacher_student_ids, teacher_subject_ids

router = APIRouter(prefix="/api/v1", tags=["teacher"])


class PublishedQuizSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    subject_id: str | None = None
    query: str = Field(default="", max_length=100)


def _initials(name: str | None) -> str:
    parts = (name or "?").split()
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


@router.get("/teacher/class-overview")
async def class_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")

    return await asyncio.to_thread(
        rpc_json_value,
        get_service_client(),
        "teacher_class_overview_metrics",
        {"p_tenant": profile.tenant_id, "p_teacher": profile.user_id},
        dict,
    )


@router.get("/teacher/quiz-sets/{quiz_set_id}/performance")
async def quiz_set_performance(
    quiz_set_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Performance report for one of the current teacher's published quizzes.

    This is deliberately scoped by tenant, creator and the teacher's *current*
    subject assignment.  A reassigned teacher cannot keep reading a former
    class's results simply by retaining a quiz-set URL.
    """
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")
    service, tid, uid = get_service_client(), profile.tenant_id, profile.user_id

    quiz = await asyncio.to_thread(
        lambda: (
            service.table("quiz_sets").select("id, title, status, subject_id, published_at")
            .eq("id", quiz_set_id).eq("tenant_id", tid).eq("created_by", uid)
            .maybe_single().execute().data
        )
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz set not found.")
    if str(quiz.get("subject_id") or "") not in teacher_subject_ids(service, profile):
        raise HTTPException(status_code=404, detail="Quiz set not found.")

    subject = await asyncio.to_thread(
        lambda: service.table("subjects").select("course_id").eq("id", quiz["subject_id"])
        .eq("tenant_id", tid).maybe_single().execute().data
    )
    if not subject:
        raise HTTPException(status_code=404, detail="Quiz subject not found.")

    def fetch_variants():
        return (
            service.table("quiz_variants")
            .select(
                "id, total_marks, quiz_variant_questions(question_id, questions(id, question_text)), "
                "quiz_attempts(id, student_id, total_score, submitted_at, status, "
                "profiles(full_name), attempt_answers(question_id, student_answer, is_correct))"
            )
            .eq("tenant_id", tid).eq("quiz_set_id", quiz_set_id).execute().data or []
        )

    def fetch_roster():
        enrollments = select_all(
            service, "enrollments", "profile_id",
            configure=lambda q: q.eq("tenant_id", tid).eq("course_id", subject["course_id"]),
        )
        ids = sorted({str(row["profile_id"]) for row in enrollments})
        if not ids:
            return []
        return select_all_in(
            service, "profiles", "id, full_name", in_column="id", values=ids,
            configure=lambda q: q.eq("tenant_id", tid).eq("role", "student"),
        )

    variants, roster_rows = await asyncio.gather(
        asyncio.to_thread(fetch_variants), asyncio.to_thread(fetch_roster)
    )
    roster = {str(row["id"]): row.get("full_name") or "Student" for row in roster_rows}
    marks = {str(row["id"]): float(row.get("total_marks") or 0) for row in variants}
    question_by_id: dict[str, str] = {}
    for variant in variants:
        for vq in variant.get("quiz_variant_questions") or []:
            question = vq.get("questions") or {}
            if question.get("id"):
                question_by_id[str(question["id"])] = question.get("question_text") or "Question"

    attempts_by_student: dict[str, list[dict]] = {}
    answer_counts: dict[str, dict[str, int]] = {}
    all_percentages: list[float] = []
    for variant in variants:
        maximum = marks.get(str(variant["id"]), 0)
        for attempt in variant.get("quiz_attempts") or []:
            student_id = str(attempt.get("student_id") or "")
            if student_id not in roster or attempt.get("status") != "graded":
                continue
            score = max(0.0, min(maximum, float(attempt.get("total_score") or 0)))
            accuracy = round(score / maximum * 100, 1) if maximum else 0
            normal = {
                "attempt_id": str(attempt["id"]), "score": score, "max_score": maximum,
                "accuracy": accuracy, "submitted_at": attempt.get("submitted_at"),
            }
            attempts_by_student.setdefault(student_id, []).append(normal)
            all_percentages.append(accuracy)
            for answer in attempt.get("attempt_answers") or []:
                if not is_answered(answer.get("student_answer")):
                    continue
                question_id = str(answer.get("question_id") or "")
                if not question_id:
                    continue
                bucket = answer_counts.setdefault(question_id, {"answered": 0, "correct": 0})
                bucket["answered"] += 1
                if answer.get("is_correct") is True:
                    bucket["correct"] += 1

    students = []
    for student_id, name in roster.items():
        attempts = sorted(attempts_by_student.get(student_id, []), key=lambda row: row.get("submitted_at") or "", reverse=True)
        latest = attempts[0] if attempts else None
        best = max(attempts, key=lambda row: row["accuracy"]) if attempts else None
        students.append({
            "student_id": student_id, "student_name": name, "attempts": len(attempts),
            "status": "completed" if attempts else "not_started",
            "latest_score": latest["score"] if latest else None,
            "latest_max_score": latest["max_score"] if latest else None,
            "latest_accuracy": latest["accuracy"] if latest else None,
            "best_accuracy": best["accuracy"] if best else None,
            "submitted_at": latest["submitted_at"] if latest else None,
        })
    students.sort(key=lambda row: (row["status"] == "not_started", row["student_name"].casefold()))
    bands = [("0–39", 0, 40), ("40–59", 40, 60), ("60–79", 60, 80), ("80–100", 80, 101)]
    question_performance = [
        {"question_id": question_id, "question_text": question_by_id.get(question_id, "Question"),
         "answered": count["answered"], "accuracy": round(count["correct"] / count["answered"] * 100, 1)}
        for question_id, count in answer_counts.items() if count["answered"]
    ]
    question_performance.sort(key=lambda row: (row["accuracy"], -row["answered"]))
    completed = sum(1 for row in students if row["status"] == "completed")
    return {
        "quiz": {**quiz, "eligible_students": len(roster)},
        "summary": {"eligible_students": len(roster), "completed_students": completed,
                    "not_started_students": len(roster) - completed, "total_attempts": len(all_percentages),
                    "average_accuracy": round(sum(all_percentages) / len(all_percentages), 1) if all_percentages else 0,
                    "highest_accuracy": max(all_percentages, default=0), "lowest_accuracy": min(all_percentages, default=0)},
        "score_distribution": [{"label": label, "count": sum(1 for p in all_percentages if low <= p < high)} for label, low, high in bands],
        "students": students,
        "question_performance": question_performance,
    }


async def published_quiz_monitor(
    profile: CurrentProfile = Depends(get_current_profile),
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    subject_id: str | None = None,
    q: str = "",
) -> dict:
    """One bounded page of published-quiz metrics owned by the teacher."""
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")
    page_size = bounded_page_size(page_size)
    page_cursor = decode_cursor(cursor)
    normalized_query = q.strip()
    if len(normalized_query) > 100:
        raise HTTPException(status_code=400, detail="Search text is too long.")
    payload = await asyncio.to_thread(
        rpc_json_value,
        get_service_client(),
        "teacher_published_quiz_metrics_page",
        {
            "p_tenant": profile.tenant_id,
            "p_teacher": profile.user_id,
            "p_limit": page_size + 1,
            "p_before_at": page_cursor.occurred_at.isoformat() if page_cursor else None,
            "p_before_id": page_cursor.row_id if page_cursor else None,
            "p_subject": subject_id,
            "p_search": normalized_query or None,
        },
        dict,
    )
    quizzes = payload.get("quizzes")
    if not isinstance(quizzes, list):
        raise RuntimeError("teacher_published_quiz_metrics_page returned an invalid payload")
    has_more = len(quizzes) > page_size
    items = quizzes[:page_size]
    next_cursor = (
        encode_cursor(items[-1]["_cursor_at"], items[-1]["id"])
        if has_more and items
        else None
    )
    for item in items:
        item.pop("_cursor_at", None)
    return {"quizzes": items, "next_cursor": next_cursor}


@router.get("/teacher/published-quizzes")
async def published_quiz_monitor_route(
    profile: CurrentProfile = Depends(get_current_profile),
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    subject_id: str | None = None,
) -> dict:
    return await published_quiz_monitor(
        profile=profile,
        cursor=cursor,
        page_size=page_size,
        subject_id=subject_id,
    )


@router.post("/teacher/published-quizzes/search")
async def search_published_quiz_monitor(
    body: PublishedQuizSearchRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    return await published_quiz_monitor(
        profile=profile,
        cursor=body.cursor,
        page_size=body.page_size,
        subject_id=body.subject_id,
        q=body.query,
    )


@router.get("/teacher/class-monitor")
async def class_monitor(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Class roster + engagement for the teacher's current subject assignments.
    Each row shows activity on quizzes this teacher created for those assigned
    subjects. Students with no attempt yet show as ``not_started``.
    """
    from datetime import date, timedelta

    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")

    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id
    empty = {
        "summary": {
            "students": 0,
            "active_week": 0,
            "class_accuracy": 0,
            "at_risk": 0,
            "not_started": 0,
            "total_attempts": 0,
        },
        "students": [],
    }

    # The institution-admin assignment is authoritative. Quiz ownership alone
    # must not keep granting a teacher access to a course after reassignment.
    assigned_subject_ids = sorted(teacher_subject_ids(service, profile))
    if not assigned_subject_ids:
        return empty

    subs = await asyncio.to_thread(
        select_all_in,
        service,
        "subjects",
        "id, course_id",
        in_column="id",
        values=assigned_subject_ids,
        configure=lambda query: query.eq("tenant_id", tid),
    )
    course_ids = list({s["course_id"] for s in subs if s.get("course_id")})
    if not course_ids:
        return empty

    enrollments = await asyncio.to_thread(
        select_all_in,
        service,
        "enrollments",
        "id, profile_id",
        in_column="course_id",
        values=course_ids,
        configure=lambda query: query.eq("tenant_id", tid),
    )
    enrolled_ids = {str(row["profile_id"]) for row in enrollments}
    if not enrolled_ids:
        return empty
    prows = await asyncio.to_thread(
        select_all_in,
        service,
        "profiles",
        "id, full_name, role",
        in_column="id",
        values=sorted(enrolled_ids),
        configure=lambda query: query.eq("tenant_id", tid)
        .eq("role", "student"),
    )
    names = {str(p["id"]): p.get("full_name") for p in prows}
    roster = set(names.keys())
    if not roster:
        return empty

    sets = await asyncio.to_thread(
        select_all_in,
        service,
        "quiz_sets",
        "id, subject_id",
        in_column="subject_id",
        values=assigned_subject_ids,
        configure=lambda query: query.eq("tenant_id", tid)
        .eq("created_by", uid),
    )
    variants: list[dict] = []
    if sets:
        variants = await asyncio.to_thread(
            select_all_in,
            service,
            "quiz_variants",
            "id, total_marks",
            in_column="quiz_set_id",
            values=[row["id"] for row in sets],
            configure=lambda query: query.eq("tenant_id", tid),
        )
    var_marks = {str(v["id"]): v.get("total_marks") for v in variants}
    attempts: list[dict] = []
    if var_marks:
        attempts = await asyncio.to_thread(
            select_all_in,
            service,
            "quiz_attempts",
            "id, student_id, variant_id, total_score, submitted_at",
            in_column="variant_id",
            values=list(var_marks),
            configure=lambda query: query.eq("tenant_id", tid)
            .eq("status", "graded"),
        )
        attempts = [
            attempt
            for attempt in attempts
            if str(attempt.get("student_id")) in roster
        ]

    agg: dict[str, dict] = {}
    for a in attempts:
        maximum_value = var_marks.get(str(a["variant_id"]))
        if not maximum_value:
            continue
        maximum = float(maximum_value)
        score = max(0.0, min(maximum, float(a.get("total_score") or 0)))
        pct = score / maximum * 100
        d = agg.setdefault(
            str(a["student_id"]),
            {"pcts": [], "score": 0.0, "maximum": 0.0, "last": None, "best": 0},
        )
        d["pcts"].append(pct)
        d["score"] += score
        d["maximum"] += maximum
        d["best"] = max(d["best"], pct)
        submitted_at = a.get("submitted_at")
        if submitted_at and (d["last"] is None or submitted_at > d["last"]):
            d["last"] = submitted_at

    week_ago = (date.today() - timedelta(days=7)).isoformat()

    engaged, not_started_rows = [], []
    total_score = total_maximum = 0.0
    active = at_risk = 0
    for sid in roster:
        name = names.get(sid) or "Student"
        d = agg.get(sid)
        if not d or not d["pcts"]:
            not_started_rows.append(
                {
                    "id": sid,
                    "name": name,
                    "initials": _initials(name),
                    "attempts": 0,
                    "accuracy": 0,
                    "best": 0,
                    "last_active": None,
                    "status": "not_started",
                }
            )
            continue
        acc = round(d["score"] / d["maximum"] * 100)
        total_score += d["score"]
        total_maximum += d["maximum"]
        if d["last"] and d["last"][:10] >= week_ago:
            active += 1
        if acc < 60:
            status_s = "at_risk"
            at_risk += 1
        elif acc >= 75:
            status_s = "strong"
        else:
            status_s = "ok"
        engaged.append(
            {
                "id": sid,
                "name": name,
                "initials": _initials(name),
                "attempts": len(d["pcts"]),
                "accuracy": acc,
                "best": d["best"],
                "last_active": d["last"],
                "status": status_s,
            }
        )

    engaged.sort(key=lambda s: s["last_active"] or "", reverse=True)
    not_started_rows.sort(key=lambda s: s["name"].lower())

    return {
        "summary": {
            "students": len(roster),
            "active_week": active,
            "class_accuracy": round(total_score / total_maximum * 100) if total_maximum else 0,
            "at_risk": at_risk,
            "not_started": len(not_started_rows),
            "total_attempts": len(attempts),
        },
        "students": engaged + not_started_rows,
    }


@router.get("/teacher/student-report/{student_id}")
def student_report(
    student_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """
    Full report for one student, scoped to THIS teacher's quizzes: overall
    accuracy, per-quiz scores, and weak areas (topic breakdown). Powers the
    'download student report' from Class monitor.
    """
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")

    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id
    if student_id not in teacher_student_ids(service, profile):
        # Do not reveal whether an arbitrary same-tenant profile exists.
        raise HTTPException(status_code=404, detail="Student not found.")
    name_row = (
        service.table("profiles")
        .select("full_name")
        .eq("id", student_id)
        .eq("tenant_id", tid)
        .eq("role", "student")
        .maybe_single()
        .execute()
    )
    if name_row is None or not name_row.data:
        raise HTTPException(status_code=404, detail="Student not found.")
    sname = name_row.data.get("full_name")
    student = {"name": sname or "Student", "initials": _initials(sname)}
    empty = {
        "student": student,
        "overall": {"accuracy": 0, "quizzes_taken": 0, "questions_answered": 0},
        "per_quiz": [],
        "weak_areas": [],
    }

    assigned_subject_ids = sorted(teacher_subject_ids(service, profile))
    sets = select_all_in(
        service,
        "quiz_sets",
        "id, title",
        in_column="subject_id",
        values=assigned_subject_ids,
        configure=lambda query: query.eq("tenant_id", tid)
        .eq("created_by", uid),
    )
    if not sets:
        return empty
    title_by_set = {s["id"]: s["title"] for s in sets}
    variants = select_all_in(
        service,
        "quiz_variants",
        "id, quiz_set_id, total_marks",
        in_column="quiz_set_id",
        values=[s["id"] for s in sets],
        configure=lambda query: query.eq("tenant_id", tid),
    )
    var_set = {v["id"]: v["quiz_set_id"] for v in variants}
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    variant_ids = [v["id"] for v in variants]
    if not variant_ids:
        return empty

    attempts = select_all_in(
        service,
        "quiz_attempts",
        "id, variant_id, total_score, submitted_at",
        in_column="variant_id",
        values=variant_ids,
        configure=lambda query: query.eq("tenant_id", tid)
        .eq("student_id", student_id)
        .eq("status", "graded"),
    )
    per_quiz, attempt_ids = [], []
    total_score = total_maximum = 0.0
    for a in attempts:
        m = var_marks.get(a["variant_id"])
        if m:
            maximum = float(m)
            score = max(0.0, min(maximum, float(a.get("total_score") or 0)))
            pct = round(score / maximum * 100)
            total_score += score
            total_maximum += maximum
        else:
            pct = 0
        per_quiz.append(
            {
                "title": title_by_set.get(var_set.get(a["variant_id"]), "Quiz"),
                "accuracy": pct,
                "date": a.get("submitted_at"),
            }
        )
        attempt_ids.append(a["id"])
    per_quiz.sort(key=lambda x: x["date"] or "", reverse=True)

    weak_areas: list[dict] = []
    answered = 0
    if attempt_ids:
        answers = select_all_in(
            service,
            "attempt_answers",
            "id, question_id, student_answer, is_correct",
            in_column="attempt_id",
            values=attempt_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )
        answers = [a for a in answers if is_answered(a.get("student_answer"))]
        answered = len(answers)
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
        agg: dict = {}
        for a in answers:
            top = topic_of.get(a["question_id"])
            if not top:
                continue
            c, t = agg.get(top, (0, 0))
            agg[top] = (c + (1 if a.get("is_correct") else 0), t + 1)
        if agg:
            names = {
                n["id"]: n["name"]
                for n in select_all_in(
                    service,
                    "topics",
                    "id, name",
                    in_column="id",
                    values=list(agg.keys()),
                    configure=lambda query: query.eq("tenant_id", tid),
                )
            }
            weak_areas = sorted(
                [
                    {"topic": names.get(k, "Topic"), "accuracy": round(v[0] / v[1] * 100), "answered": v[1]}
                    for k, v in agg.items()
                    if round(v[0] / v[1] * 100) < 60
                ],
                key=lambda x: x["accuracy"],
            )

    return {
        "student": student,
        "overall": {
            "accuracy": round(total_score / total_maximum * 100)
            if total_maximum
            else 0,
            "quizzes_taken": len(attempts),
            "questions_answered": answered,
        },
        "per_quiz": per_quiz,
        "weak_areas": weak_areas,
    }
