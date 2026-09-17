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

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all, select_all_in
from app.services.teacher_access import teacher_student_ids, teacher_subject_ids

router = APIRouter(prefix="/api/v1", tags=["teacher"])

def _initials(name: str | None) -> str:
    parts = (name or "?").split()
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


@router.get("/teacher/class-overview")
async def class_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")

    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id
    empty = {
        "class_accuracy": 0,
        "students": 0,
        "at_risk": 0,
        "total_attempts": 0,
        "accuracy_by_quiz": [],
        "needs_attention": [],
        "top_performers": [],
        "pipeline": {
            "pending_review": 0,
            "approved": 0,
            "rejected": 0,
            "needs_edit": 0,
        },
        "activity_trend": [],
        "score_distribution": [],
        "content": {"documents": 0, "quiz_sets": 0, "published": 0, "drafts": 0},
    }

    # Stage 1: quiz_sets — every later query needs `set_ids` from this, so it
    # has to run alone first.
    def fetch_sets():
        return select_all(
            service,
            "quiz_sets",
            "id, title, status",
            configure=lambda query: query.eq("tenant_id", tid).eq(
                "created_by", uid
            ),
        )

    def fetch_documents():
        return select_all(
            service,
            "documents",
            "id",
            configure=lambda query: query.eq("tenant_id", tid).eq(
                "uploaded_by", uid
            ),
        )

    sets, document_rows = await asyncio.gather(
        asyncio.to_thread(fetch_sets), asyncio.to_thread(fetch_documents)
    )
    content = {
        "documents": len(document_rows),
        "quiz_sets": len(sets),
        "published": sum(1 for row in sets if row.get("status") == "published"),
        "drafts": sum(1 for row in sets if row.get("status") == "draft"),
    }
    set_ids = [s["id"] for s in sets]
    if not set_ids:
        return {**empty, "content": content}
    title_by_set = {s["id"]: s["title"] for s in sets}

    # Stage 2: quiz_variants — needs `set_ids` from stage 1.
    def fetch_variants():
        return select_all_in(
            service,
            "quiz_variants",
            "id, quiz_set_id, total_marks",
            in_column="quiz_set_id",
            values=set_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )

    variants = await asyncio.to_thread(fetch_variants)
    var_set = {v["id"]: v["quiz_set_id"] for v in variants}
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    variant_ids = [v["id"] for v in variants]
    if not variant_ids:
        return {**empty, "content": content}

    # Stage 3: these reads are independent. The shared Supabase client uses a
    # thread-safe HTTP/1.1 pool, so overlap their network wait safely.
    def fetch_attempts():
        return select_all_in(
            service,
            "quiz_attempts",
            "id, student_id, variant_id, total_score, submitted_at",
            in_column="variant_id",
            values=variant_ids,
            configure=lambda query: query.eq("tenant_id", tid)
            .eq("status", "graded"),
        )

    def fetch_variant_questions():
        return select_all_in(
            service,
            "quiz_variant_questions",
            "id, question_id",
            in_column="variant_id",
            values=variant_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )

    attempts, vq = await asyncio.gather(
        asyncio.to_thread(fetch_attempts),
        asyncio.to_thread(fetch_variant_questions),
    )

    by_set: dict[str, list[float]] = {}
    by_student: dict[str, list[float]] = {}
    total_score = total_maximum = 0.0
    attempt_pcts: list[float] = []
    day_counts: dict[str, int] = {}  # submitted date (YYYY-MM-DD) -> attempts
    for a in attempts:
        vm = var_marks.get(a["variant_id"])
        if not vm:
            continue
        maximum = float(vm)
        score = max(0.0, min(maximum, float(a.get("total_score") or 0)))
        pct = score / maximum * 100
        total_score += score
        total_maximum += maximum
        sid = var_set.get(a["variant_id"])
        if sid:
            s = by_set.get(sid, [0.0, 0.0, 0.0])
            by_set[sid] = [s[0] + score, s[1] + maximum, s[2] + 1]
        st = by_student.get(a["student_id"], [0.0, 0.0, 0.0])
        by_student[a["student_id"]] = [st[0] + score, st[1] + maximum, st[2] + 1]
        attempt_pcts.append(pct)
        submitted = a.get("submitted_at")
        if submitted:
            day = str(submitted)[:10]
            day_counts[day] = day_counts.get(day, 0) + 1

    accuracy_by_quiz = sorted(
        [
            {
                "set_id": sid,
                "title": title_by_set.get(sid, "Quiz"),
                "accuracy": round(v[0] / v[1] * 100),
                "attempts": int(v[2]),
            }
            for sid, v in by_set.items()
        ],
        key=lambda x: -x["attempts"],
    )

    qids = list({r["question_id"] for r in vq})

    # Stage 4: profile and question reads are independent as well.
    def fetch_profiles():
        if not by_student:
            return []
        return select_all_in(
            service,
            "profiles",
            "id, full_name",
            in_column="id",
            values=list(by_student.keys()),
            configure=lambda query: query.eq("tenant_id", tid)
            .eq("role", "student"),
        )

    def fetch_questions():
        if not qids:
            return []
        return select_all_in(
            service,
            "questions",
            "id, review_status",
            in_column="id",
            values=qids,
            configure=lambda query: query.eq("tenant_id", tid),
        )

    profs, qrows = await asyncio.gather(
        asyncio.to_thread(fetch_profiles), asyncio.to_thread(fetch_questions)
    )
    names = {p["id"]: p.get("full_name") for p in profs}

    students = []
    for sid, v in by_student.items():
        acc = round(v[0] / v[1] * 100)
        name = names.get(sid) or "Student"
        students.append(
            {
                "name": name,
                "initials": _initials(name),
                "accuracy": acc,
                "note": f"{int(v[2])} test{'s' if v[2] != 1 else ''} · {acc}% avg",
            }
        )
    at_risk_students = [s for s in students if s["accuracy"] < 60]
    needs_attention = sorted(at_risk_students, key=lambda x: x["accuracy"])[:6]
    # Best-scoring students (highest average accuracy first).
    top_performers = sorted(students, key=lambda x: -x["accuracy"])[:5]

    # Review pipeline: how many of the teacher's questions sit in each state.
    pipeline = {
        "pending_review": 0,
        "approved": 0,
        "rejected": 0,
        "needs_edit": 0,
    }
    for q in qrows:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    class_accuracy = round(total_score / total_maximum * 100) if total_maximum else 0

    # Activity trend: quizzes taken per day over the last 14 days (zero-filled),
    # so the frontend can draw a clean bar chart without gaps.
    from datetime import date, timedelta

    today = date.today()
    activity_trend = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "count": day_counts.get((today - timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(13, -1, -1)
    ]

    # Score distribution: how many graded attempts fall in each score band.
    bands = [("0–39", 0, 40), ("40–59", 40, 60), ("60–79", 60, 80), ("80–100", 80, 101)]
    score_distribution = [
        {"label": label, "count": sum(1 for p in attempt_pcts if lo <= p < hi)}
        for label, lo, hi in bands
    ]
    return {
        "class_accuracy": class_accuracy,
        "students": len(by_student),
        "at_risk": len(at_risk_students),
        "total_attempts": len(attempts),
        "accuracy_by_quiz": accuracy_by_quiz,
        "needs_attention": needs_attention,
        "top_performers": top_performers,
        "pipeline": pipeline,
        "activity_trend": activity_trend,
        "score_distribution": score_distribution,
        "content": content,
    }


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
            "id, question_id, is_correct",
            in_column="attempt_id",
            values=attempt_ids,
            configure=lambda query: query.eq("tenant_id", tid),
        )
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
