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

router = APIRouter(prefix="/api/v1", tags=["teacher"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


def _initials(name: str | None) -> str:
    parts = (name or "?").split()
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


@router.get("/teacher/class-overview")
async def class_overview(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only.")

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
        "pipeline": {"pending_review": 0, "approved": 0, "rejected": 0},
    }

    # Stage 1: quiz_sets — every later query needs `set_ids` from this, so it
    # has to run alone first.
    def fetch_sets():
        return (
            service.table("quiz_sets")
            .select("id, title")
            .eq("tenant_id", tid)
            .eq("created_by", uid)
            .execute()
            .data
            or []
        )

    sets = await asyncio.to_thread(fetch_sets)
    set_ids = [s["id"] for s in sets]
    if not set_ids:
        return empty
    title_by_set = {s["id"]: s["title"] for s in sets}

    # Stage 2: quiz_variants — needs `set_ids` from stage 1.
    def fetch_variants():
        return (
            service.table("quiz_variants")
            .select("id, quiz_set_id, total_marks")
            .in_("quiz_set_id", set_ids)
            .execute()
            .data
            or []
        )

    variants = await asyncio.to_thread(fetch_variants)
    var_set = {v["id"]: v["quiz_set_id"] for v in variants}
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    variant_ids = [v["id"] for v in variants]
    if not variant_ids:
        return empty

    # Stage 3: quiz_attempts and quiz_variant_questions both only need
    # `variant_ids` from stage 2, not each other's result — run them at the
    # same time. `supabase-py`'s `.execute()` is a blocking network call, so
    # `asyncio.to_thread` runs each one on its own thread and `asyncio.gather`
    # waits for both instead of doing them one after another.
    def fetch_attempts():
        return (
            service.table("quiz_attempts")
            .select("student_id, variant_id, total_score")
            .in_("variant_id", variant_ids)
            .eq("status", "graded")
            .execute()
            .data
            or []
        )

    def fetch_variant_questions():
        return (
            service.table("quiz_variant_questions")
            .select("question_id")
            .in_("variant_id", variant_ids)
            .execute()
            .data
            or []
        )

    attempts, vq = await asyncio.gather(
        *[asyncio.to_thread(fn) for fn in (fetch_attempts, fetch_variant_questions)]
    )

    by_set: dict[str, list[int]] = {}
    by_student: dict[str, list[int]] = {}
    all_pcts: list[int] = []
    for a in attempts:
        vm = var_marks.get(a["variant_id"])
        if not vm:
            continue
        pct = max(0, min(100, round((a.get("total_score") or 0) / vm * 100)))
        sid = var_set.get(a["variant_id"])
        if sid:
            s = by_set.get(sid, [0, 0])
            by_set[sid] = [s[0] + pct, s[1] + 1]
        st = by_student.get(a["student_id"], [0, 0])
        by_student[a["student_id"]] = [st[0] + pct, st[1] + 1]
        all_pcts.append(pct)

    accuracy_by_quiz = sorted(
        [
            {
                "set_id": sid,
                "title": title_by_set.get(sid, "Quiz"),
                "accuracy": round(v[0] / v[1]),
                "attempts": v[1],
            }
            for sid, v in by_set.items()
        ],
        key=lambda x: -x["attempts"],
    )

    qids = list({r["question_id"] for r in vq})

    # Stage 4: profiles (student names) and questions (review status) are
    # independent of each other — run concurrently.
    def fetch_profiles():
        if not by_student:
            return []
        return (
            service.table("profiles")
            .select("id, full_name")
            .in_("id", list(by_student.keys()))
            .execute()
            .data
            or []
        )

    def fetch_questions():
        if not qids:
            return []
        return (
            service.table("questions")
            .select("review_status")
            .in_("id", qids)
            .execute()
            .data
            or []
        )

    profs, qrows = await asyncio.gather(
        *[asyncio.to_thread(fn) for fn in (fetch_profiles, fetch_questions)]
    )
    names = {p["id"]: p.get("full_name") for p in profs}

    students = []
    for sid, v in by_student.items():
        acc = round(v[0] / v[1])
        name = names.get(sid) or "Student"
        students.append(
            {
                "name": name,
                "initials": _initials(name),
                "accuracy": acc,
                "note": f"{v[1]} test{'s' if v[1] != 1 else ''} · {acc}% avg",
            }
        )
    needs_attention = sorted(
        [s for s in students if s["accuracy"] < 60], key=lambda x: x["accuracy"]
    )[:6]
    # Best-scoring students (highest average accuracy first).
    top_performers = sorted(students, key=lambda x: -x["accuracy"])[:5]

    # Review pipeline: how many of the teacher's questions sit in each state.
    pipeline = {"pending_review": 0, "approved": 0, "rejected": 0}
    for q in qrows:
        st = q.get("review_status")
        if st in pipeline:
            pipeline[st] += 1

    class_accuracy = round(sum(all_pcts) / len(all_pcts)) if all_pcts else 0
    return {
        "class_accuracy": class_accuracy,
        "students": len(by_student),
        "at_risk": len(needs_attention),
        "total_attempts": len(all_pcts),
        "accuracy_by_quiz": accuracy_by_quiz,
        "needs_attention": needs_attention,
        "top_performers": top_performers,
        "pipeline": pipeline,
    }


@router.get("/teacher/class-monitor")
async def class_monitor(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """
    Class roster + engagement for the teacher. The 'class' is every student
    enrolled in the courses the teacher builds quizzes for; each row shows their
    activity on the teacher's quizzes (attempts, accuracy, last active, status).
    Students with no attempt yet show as 'not started'. Real data only.
    """
    from datetime import date, timedelta

    if profile.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only.")

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

    # Stage 1: quiz_sets — every later query needs `set_ids`/`subject_ids`
    # from this, so it has to run alone first.
    def fetch_sets():
        return (
            service.table("quiz_sets")
            .select("id, subject_id")
            .eq("tenant_id", tid)
            .eq("created_by", uid)
            .execute()
            .data
            or []
        )

    sets = await asyncio.to_thread(fetch_sets)
    if not sets:
        return empty
    set_ids = [s["id"] for s in sets]

    # The teacher's quizzes -> subjects -> courses -> enrolled students (the class).
    subject_ids = list({s["subject_id"] for s in sets if s.get("subject_id")})

    # Stage 2: subjects (-> course_ids) and quiz_variants (-> variant_ids)
    # each only need stage 1's output, not each other's — run concurrently.
    def fetch_subjects():
        if not subject_ids:
            return []
        return (
            service.table("subjects").select("id, course_id").in_("id", subject_ids).execute().data
            or []
        )

    def fetch_variants():
        return (
            service.table("quiz_variants")
            .select("id, total_marks")
            .in_("quiz_set_id", set_ids)
            .execute()
            .data
            or []
        )

    subs, variants = await asyncio.gather(
        *[asyncio.to_thread(fn) for fn in (fetch_subjects, fetch_variants)]
    )
    course_ids = list({s["course_id"] for s in subs if s.get("course_id")})
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    variant_ids = [v["id"] for v in variants]

    # Stage 3: enrollments (needs course_ids) and quiz_attempts (needs
    # variant_ids) are independent of each other — run concurrently.
    def fetch_enrollments():
        if not course_ids:
            return []
        return (
            service.table("enrollments")
            .select("profile_id")
            .eq("tenant_id", tid)
            .in_("course_id", course_ids)
            .execute()
            .data
            or []
        )

    def fetch_attempts():
        if not variant_ids:
            return []
        return (
            service.table("quiz_attempts")
            .select("student_id, variant_id, total_score, submitted_at")
            .in_("variant_id", variant_ids)
            .eq("status", "graded")
            .execute()
            .data
            or []
        )

    enr, attempts = await asyncio.gather(
        *[asyncio.to_thread(fn) for fn in (fetch_enrollments, fetch_attempts)]
    )
    roster: set[str] = {e["profile_id"] for e in enr}
    # Anyone who attempted counts as part of the class too.
    for a in attempts:
        roster.add(a["student_id"])
    if not roster:
        return empty

    agg: dict[str, dict] = {}
    for a in attempts:
        m = var_marks.get(a["variant_id"])
        if not m:
            continue
        pct = max(0, min(100, round((a.get("total_score") or 0) / m * 100)))
        d = agg.setdefault(a["student_id"], {"pcts": [], "last": None, "best": 0})
        d["pcts"].append(pct)
        d["best"] = max(d["best"], pct)
        sa = a.get("submitted_at")
        if sa and (d["last"] is None or sa > d["last"]):
            d["last"] = sa

    # Stage 4: profiles — needs the merged roster from stage 3.
    def fetch_profiles():
        return (
            service.table("profiles")
            .select("id, full_name, role")
            .in_("id", list(roster))
            .execute()
            .data
            or []
        )

    prows = await asyncio.to_thread(fetch_profiles)
    # The class roster is students only — exclude any staff who happen to be
    # enrolled (e.g. a teacher enrolled in their own course for testing).
    names = {p["id"]: p.get("full_name") for p in prows if p.get("role") == "student"}
    roster = set(names.keys())
    if not roster:
        return empty
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    engaged, not_started_rows = [], []
    all_pcts: list[int] = []
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
        acc = round(sum(d["pcts"]) / len(d["pcts"]))
        all_pcts.extend(d["pcts"])
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
            "class_accuracy": round(sum(all_pcts) / len(all_pcts)) if all_pcts else 0,
            "at_risk": at_risk,
            "not_started": len(not_started_rows),
            "total_attempts": len(all_pcts),
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
    if profile.role not in STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff only.")

    service = get_service_client()
    tid, uid = profile.tenant_id, profile.user_id
    name_row = (
        service.table("profiles")
        .select("full_name")
        .eq("id", student_id)
        .eq("tenant_id", tid)
        .maybe_single()
        .execute()
    )
    sname = (name_row.data or {}).get("full_name") if name_row else None
    student = {"name": sname or "Student", "initials": _initials(sname)}
    empty = {
        "student": student,
        "overall": {"accuracy": 0, "quizzes_taken": 0, "questions_answered": 0},
        "per_quiz": [],
        "weak_areas": [],
    }

    sets = (
        service.table("quiz_sets")
        .select("id, title")
        .eq("tenant_id", tid)
        .eq("created_by", uid)
        .execute()
        .data
        or []
    )
    if not sets:
        return empty
    title_by_set = {s["id"]: s["title"] for s in sets}
    variants = (
        service.table("quiz_variants")
        .select("id, quiz_set_id, total_marks")
        .in_("quiz_set_id", [s["id"] for s in sets])
        .execute()
        .data
        or []
    )
    var_set = {v["id"]: v["quiz_set_id"] for v in variants}
    var_marks = {v["id"]: v.get("total_marks") for v in variants}
    variant_ids = [v["id"] for v in variants]
    if not variant_ids:
        return empty

    attempts = (
        service.table("quiz_attempts")
        .select("id, variant_id, total_score, submitted_at")
        .in_("variant_id", variant_ids)
        .eq("student_id", student_id)
        .eq("status", "graded")
        .execute()
        .data
        or []
    )
    per_quiz, all_pcts, attempt_ids = [], [], []
    for a in attempts:
        m = var_marks.get(a["variant_id"])
        pct = max(0, min(100, round((a.get("total_score") or 0) / m * 100))) if m else 0
        per_quiz.append(
            {
                "title": title_by_set.get(var_set.get(a["variant_id"]), "Quiz"),
                "accuracy": pct,
                "date": a.get("submitted_at"),
            }
        )
        all_pcts.append(pct)
        attempt_ids.append(a["id"])
    per_quiz.sort(key=lambda x: x["date"] or "", reverse=True)

    weak_areas: list[dict] = []
    answered = 0
    if attempt_ids:
        answers = (
            service.table("attempt_answers")
            .select("question_id, is_correct")
            .in_("attempt_id", attempt_ids)
            .execute()
            .data
            or []
        )
        answered = len(answers)
        qids = list({a["question_id"] for a in answers})
        qrows = (
            service.table("questions").select("id, topic_id").in_("id", qids).execute().data or []
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
                for n in (
                    service.table("topics").select("id, name").in_("id", list(agg.keys())).execute().data
                    or []
                )
            }
            weak_areas = sorted(
                [
                    {"topic": names.get(k, "Topic"), "accuracy": round(v[0] / v[1] * 100), "answered": v[1]}
                    for k, v in agg.items()
                ],
                key=lambda x: x["accuracy"],
            )

    return {
        "student": student,
        "overall": {
            "accuracy": round(sum(all_pcts) / len(all_pcts)) if all_pcts else 0,
            "quizzes_taken": len(attempts),
            "questions_answered": answered,
        },
        "per_quiz": per_quiz,
        "weak_areas": weak_areas,
    }
