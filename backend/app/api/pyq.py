"""Student "Mock Test & PYQ" surface (KB-D).

One flow for all three paper types (PYQ / MTP / RTP): pick a type, a subject, then
optionally a chapter and question type and how many questions; the server pulls a
RANDOM matching set from the frozen `paper_questions` bank and grades it. All access
is limited to the student's enrolled subjects within their tenant. Gated by
PAPER_BANK_ENABLED (404 when off).
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.role_checks import require_staff
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all, select_all_in
from app.services.descriptive_grader import grade_descriptive
from app.services.grading import grade_answer
from app.services.selector import enrolled_subject_ids

router = APIRouter(prefix="/api/v1/papers", tags=["papers"])

_PAPER_TYPES = {"pyq", "mtp", "rtp"}
_MAX_QUESTIONS = 50


def _require_enabled() -> None:
    if not getattr(get_settings(), "paper_bank_enabled", False):
        raise HTTPException(status_code=404, detail="Not found.")


def _valid_type(paper_type: str) -> str:
    if paper_type not in _PAPER_TYPES:
        raise HTTPException(status_code=400, detail="Unknown paper type.")
    return paper_type


def _require_student(profile: CurrentProfile) -> None:
    if profile.role != "student":
        raise HTTPException(status_code=403, detail="Students only.")


def _enrolled_or_404(service, profile: CurrentProfile, subject_id: str) -> None:
    if subject_id not in enrolled_subject_ids(service, profile):
        raise HTTPException(status_code=404, detail="Subject not found.")


class StartRequest(BaseModel):
    paper_type: str
    subject_id: str
    chapter_id: str | None = None
    question_type: str | None = None
    count: int = 10


class SubmittedAnswer(BaseModel):
    question_id: str
    student_answer: Any = None


class SubmitRequest(BaseModel):
    answers: list[SubmittedAnswer] = Field(min_length=1, max_length=_MAX_QUESTIONS)


def _bank_rows(service, profile: CurrentProfile, req: StartRequest, columns: str) -> list[dict]:
    def configure(q):
        q = q.eq("tenant_id", profile.tenant_id).eq("paper_type", req.paper_type)
        q = q.eq("subject_id", req.subject_id)
        if req.chapter_id:
            q = q.eq("chapter_id", req.chapter_id)
        if req.question_type:
            q = q.eq("type", req.question_type)
        return q
    return select_all(service, "paper_questions", columns, configure=configure)


@router.get("/bank")
def paper_bank_summary(profile: CurrentProfile = Depends(get_current_profile)) -> dict:
    """Teacher log: what PYQ/MTP/RTP the tenant has in the student bank, by subject."""
    _require_enabled()
    require_staff(profile, action="view the paper bank")
    service = get_service_client()
    rows = select_all(
        service, "paper_questions", "paper_type, subject_id",
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    )
    subject_ids = sorted({r["subject_id"] for r in rows})
    names: dict[str, str] = {}
    if subject_ids:
        for s in select_all_in(
            service, "subjects", "id, name", in_column="id", values=subject_ids,
            configure=lambda q: q.eq("tenant_id", profile.tenant_id),
        ):
            names[s["id"]] = s["name"]
    per: dict[str, dict] = {}
    for r in rows:
        sid = r["subject_id"]
        entry = per.setdefault(sid, {"subject_id": sid, "subject_name": names.get(sid, "Subject"),
                                     "pyq": 0, "mtp": 0, "rtp": 0, "total": 0})
        pt = r.get("paper_type")
        if pt in ("pyq", "mtp", "rtp"):
            entry[pt] += 1
            entry["total"] += 1
    subjects = sorted(per.values(), key=lambda e: e["subject_name"].lower())
    totals = {
        "pyq": sum(s["pyq"] for s in subjects),
        "mtp": sum(s["mtp"] for s in subjects),
        "rtp": sum(s["rtp"] for s in subjects),
        "total": sum(s["total"] for s in subjects),
    }
    return {"totals": totals, "subjects": subjects}


@router.get("/subjects")
def paper_subjects(
    paper_type: str, profile: CurrentProfile = Depends(get_current_profile)
) -> list[dict]:
    """Enrolled subjects with the count of questions available for this paper type."""
    _require_enabled()
    _require_student(profile)
    _valid_type(paper_type)
    service = get_service_client()
    subject_ids = sorted(enrolled_subject_ids(service, profile))
    if not subject_ids:
        return []
    subjects = select_all_in(
        service, "subjects", "id, name", in_column="id", values=subject_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    )
    rows = select_all_in(
        service, "paper_questions", "subject_id",
        in_column="subject_id", values=subject_ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id).eq("paper_type", paper_type),
    )
    counts = Counter(r["subject_id"] for r in rows)
    out = [
        {"subject_id": s["id"], "subject_name": s["name"], "count": counts.get(s["id"], 0)}
        for s in subjects
    ]
    out.sort(key=lambda item: item["subject_name"].lower())
    return out


@router.get("/filters")
def paper_filters(
    paper_type: str, subject_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Chapters and question types (with counts) available for a subject + type."""
    _require_enabled()
    _require_student(profile)
    _valid_type(paper_type)
    service = get_service_client()
    _enrolled_or_404(service, profile, subject_id)
    rows = select_all(
        service, "paper_questions", "chapter_id, type",
        configure=lambda q: q.eq("tenant_id", profile.tenant_id)
        .eq("paper_type", paper_type).eq("subject_id", subject_id),
    )
    chapter_counts = Counter(r.get("chapter_id") for r in rows if r.get("chapter_id"))
    type_counts = Counter(r.get("type") for r in rows if r.get("type"))
    chapters = []
    if chapter_counts:
        names = select_all_in(
            service, "chapters", "id, name", in_column="id",
            values=list(chapter_counts), configure=lambda q: q.eq("tenant_id", profile.tenant_id),
        )
        name_by = {c["id"]: c["name"] for c in names}
        chapters = sorted(
            ({"chapter_id": cid, "chapter_name": name_by.get(cid, "Chapter"), "count": n}
             for cid, n in chapter_counts.items()),
            key=lambda c: c["chapter_name"].lower(),
        )
    return {
        "total": len(rows),
        "chapters": chapters,
        "question_types": [{"type": t, "count": n} for t, n in sorted(type_counts.items())],
    }


@router.post("/start")
def paper_start(
    body: StartRequest, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """A RANDOM set of matching questions to take, WITHOUT the correct answers."""
    _require_enabled()
    _require_student(profile)
    _valid_type(body.paper_type)
    service = get_service_client()
    _enrolled_or_404(service, profile, body.subject_id)
    count = max(1, min(int(body.count or 10), _MAX_QUESTIONS))
    rows = _bank_rows(
        service, profile, body,
        "id, type, question_text, options, marks, paper_type, exam, year",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No questions match this selection yet.")
    chosen = random.sample(rows, min(count, len(rows)))
    return {
        "paper_type": body.paper_type,
        "requested": count,
        "available": len(rows),
        "questions": [
            {
                "id": r["id"], "type": r["type"], "question_text": r["question_text"],
                "options": r.get("options"), "marks": r.get("marks") or 1,
                "exam": r.get("exam"), "year": r.get("year"),
            }
            for r in chosen
        ],
    }


@router.post("/submit")
def paper_submit(
    body: SubmitRequest, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    """Auto-grade a taken paper set and return the scorecard with correct answers."""
    _require_enabled()
    _require_student(profile)
    service = get_service_client()
    ids = [a.question_id for a in body.answers]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Each question can be submitted only once.")
    enrolled = enrolled_subject_ids(service, profile)
    rows = select_all_in(
        service, "paper_questions",
        "id, type, question_text, options, correct_answer, explanation, marks, "
        "subject_id, model_answer, answer_summary",
        in_column="id", values=ids,
        configure=lambda q: q.eq("tenant_id", profile.tenant_id),
    )
    by_id = {r["id"]: r for r in rows if r.get("subject_id") in enrolled}
    answer_by_id = {a.question_id: a.student_answer for a in body.answers}

    # Descriptive answers are graded by AI in one batched call; objective answers
    # are graded deterministically. A student who covers >= 90% of the model answer's
    # key points earns the full marks for that descriptive question.
    descriptive_items = [
        {"question_id": qid, "answer_summary": by_id[qid].get("answer_summary"),
         "model_answer": by_id[qid].get("model_answer"), "student_answer": answer_by_id.get(qid)}
        for qid in ids
        if qid in by_id and by_id[qid].get("type") == "descriptive"
    ]
    descriptive_pass = (
        grade_descriptive(descriptive_items, tenant_id=profile.tenant_id)
        if descriptive_items else {}
    )

    results: list[dict] = []
    score = 0.0
    total = 0.0
    for qid in ids:
        r = by_id.get(qid)
        if not r:
            continue  # not the student's subject / not found - skip silently
        marks = float(r.get("marks") or 1)
        total += marks
        student_answer = answer_by_id.get(qid)
        if r["type"] == "descriptive":
            is_correct = bool(descriptive_pass.get(qid))
            awarded = marks if is_correct else 0.0
            correct_display = r.get("model_answer") or r.get("answer_summary")
        else:
            is_correct, awarded = grade_answer(
                {"type": r["type"], "correct_answer": r["correct_answer"], "marks": marks},
                student_answer,
            )
            correct_display = r["correct_answer"]
        score += awarded
        results.append({
            "question_id": qid, "type": r["type"], "question_text": r["question_text"],
            "options": r.get("options"), "student_answer": student_answer,
            "correct_answer": correct_display, "explanation": r.get("explanation"),
            "is_correct": is_correct, "marks_awarded": awarded,
        })
    if not results:
        raise HTTPException(status_code=404, detail="No gradeable questions found.")
    return {
        "score": round(score, 2),
        "total": round(total, 2),
        "correct": sum(1 for x in results if x["is_correct"]),
        "count": len(results),
        "results": results,
    }
