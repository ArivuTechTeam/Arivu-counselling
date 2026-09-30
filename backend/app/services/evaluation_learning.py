"""Best-effort learning data derived only from committed evaluation results."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from app.lib.supabase_queries import select_all, select_all_in
from app.services.evaluation_references import normalize_question_ref

LEARNING_CATEGORIES = {
    "not_attempted", "conceptual", "application", "presentation",
    "calculation", "step_loss", "keyword", "format", "time_management",
}


@dataclass(frozen=True)
class LearningContext:
    tenant_id: str
    evaluation_id: str
    student_id: str
    subject_id: str
    paper_id: str
    overall_feedback: str
    questions: list[dict]
    rubric: list[dict]
    chapter_names: list[str]


def _normalise(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _number(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _category(row: dict) -> str:
    category = str(row.get("category") or "").strip().lower()
    if category in LEARNING_CATEGORIES - {"not_attempted"}:
        return category
    text = _normalise(row.get("criterion"))
    if re.search(r"\b(present|neat|heading)", text):
        return "presentation"
    if re.search(r"\b(calc|comput|figure)", text):
        return "calculation"
    if re.search(r"\b(step|working|method)", text):
        return "step_loss"
    if re.search(r"\b(format|structure)", text):
        return "format"
    if re.search(r"\b(keyword|term)", text):
        return "keyword"
    return "conceptual"


def _severity(marks_lost: float) -> str:
    return "minor" if marks_lost < 1 else "moderate" if marks_lost < 3 else "major"


def _signature(topic: str, category: str, criterion_key: str) -> str:
    canonical = "|".join((_normalise(topic), _normalise(category), _normalise(criterion_key)))
    return sha256(canonical.encode("utf-8")).hexdigest()


def resolve_chapter_name(rubric_topic: object, question_text: object,
                         chapter_names: list[str]) -> str:
    """Rubric topic, longest tenant-subject chapter match, then stable fallback."""
    explicit = str(rubric_topic or "").strip()
    if explicit:
        return explicit[:200]
    signal = _normalise(question_text)
    matches = [str(name).strip() for name in chapter_names
               if str(name).strip() and _normalise(name) in signal]
    return (max(matches, key=len)[:200] if matches else "Other topics")


def build_mistake_specs(context: LearningContext) -> list[dict]:
    rubric = {normalize_question_ref(row.get("question_ref")): row
              for row in context.rubric if isinstance(row, dict)}
    specs: list[dict] = []
    for result in context.questions:
        if result.get("not_counted") or result.get("not_evaluated"):
            continue
        possible = _number(result.get("marks_possible"))
        obtained = min(_number(result.get("marks_obtained")), possible)
        gap = round(max(0.0, possible - obtained), 1)
        if gap <= 0:
            continue
        item = rubric.get(normalize_question_ref(result.get("question_ref")), {})
        topic = resolve_chapter_name(
            item.get("topic"), result.get("question_text"), context.chapter_names,
        )
        qref = str(result.get("question_ref") or "").strip()
        if result.get("not_attempted"):
            criterion_key = "not_attempted"
            description = f"Question {qref} was not attempted." if qref else "This question was not attempted."
            specs.append({
                "question_result_id": result.get("id"), "category": "not_attempted",
                "severity": _severity(gap), "description": description,
                "marks_lost": gap,
                "suggestion": "Attempt the question, even partially. Start with the relevant provision, formula, format, or first working step.",
                "chapter_name": topic, "criterion_key": criterion_key,
                "signature": _signature(topic, "not_attempted", criterion_key),
            })
            continue

        deficient: list[tuple[dict, float]] = []
        for row in result.get("criteria_breakdown") or []:
            if not isinstance(row, dict):
                continue
            available = _number(row.get("marks_available", row.get("marks")))
            awarded = min(_number(row.get("marks_awarded")), available)
            if available - awarded > 0:
                deficient.append((row, available - awarded))
        if not deficient:
            criterion_key = "overall_answer"
            description = str(result.get("feedback") or context.overall_feedback or
                              "The answer did not fully meet the expected answer requirements.").strip()
            specs.append({
                "question_result_id": result.get("id"), "category": "conceptual",
                "severity": _severity(gap), "description": description,
                "marks_lost": gap,
                "suggestion": "Compare your answer with the expected points and complete the missing requirement.",
                "chapter_name": topic, "criterion_key": criterion_key,
                "signature": _signature(topic, "conceptual", criterion_key),
            })
            continue

        raw_total = sum(deficit for _, deficit in deficient)
        allocated = 0.0
        for index, (row, deficit) in enumerate(deficient):
            if index == len(deficient) - 1:
                loss = round(max(0.0, gap - allocated), 1)
            else:
                loss = round(gap * deficit / raw_total, 1) if raw_total else 0.0
                loss = min(loss, round(max(0.0, gap - allocated), 1))
                allocated = round(allocated + loss, 1)
            if loss <= 0:
                continue
            criterion = str(row.get("criterion") or "Answer requirement").strip()
            category = _category(row)
            criterion_key = _normalise(criterion)[:120] or "answer_requirement"
            specs.append({
                "question_result_id": result.get("id"), "category": category,
                "severity": _severity(loss),
                "description": str(row.get("comment") or "").strip() or criterion
                or context.overall_feedback,
                "marks_lost": loss,
                "suggestion": str(row.get("correct_treatment") or "").strip(),
                "chapter_name": topic, "criterion_key": criterion_key,
                "signature": _signature(topic, category, criterion_key),
            })
    return specs


def load_learning_context(service, *, tenant_id: str, evaluation_id: str) -> LearningContext:
    evaluation = (service.table("handwritten_evaluations")
                  .select("id,tenant_id,submission_id,overall_feedback,status")
                  .eq("id", evaluation_id).eq("tenant_id", tenant_id)
                  .eq("status", "completed").maybe_single().execute().data)
    if not evaluation:
        raise RuntimeError("Committed evaluation not found.")
    submission = (service.table("handwritten_submissions")
                  .select("id,tenant_id,student_id,evaluation_paper_id,status")
                  .eq("id", evaluation["submission_id"]).eq("tenant_id", tenant_id)
                  .eq("status", "evaluated").maybe_single().execute().data)
    if not submission:
        raise RuntimeError("Evaluation submission is not fully committed.")
    paper = (service.table("evaluation_papers")
             .select("id,tenant_id,subject_id,structured_qa")
             .eq("id", submission["evaluation_paper_id"]).eq("tenant_id", tenant_id)
             .maybe_single().execute().data)
    if not paper:
        raise RuntimeError("Evaluation paper not found.")
    questions = select_all(
        service, "handwritten_question_evaluations",
        "id,tenant_id,evaluation_id,question_ref,question_text,marks_obtained,marks_possible,not_attempted,not_evaluated,not_counted,feedback,student_answer_excerpt,criteria_breakdown",
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("evaluation_id", evaluation_id),
    )
    chapters = select_all(
        service, "chapters", "id,name",
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("subject_id", paper["subject_id"]),
    )
    return LearningContext(
        tenant_id=tenant_id, evaluation_id=evaluation_id,
        student_id=str(submission["student_id"]), subject_id=str(paper["subject_id"]),
        paper_id=str(paper["id"]), overall_feedback=str(evaluation.get("overall_feedback") or ""),
        questions=questions, rubric=paper.get("structured_qa") or [],
        chapter_names=[str(row["name"]) for row in chapters if row.get("name")],
    )


def create_mistakes(service, *, tenant_id: str, evaluation_id: str) -> LearningContext:
    context = load_learning_context(service, tenant_id=tenant_id, evaluation_id=evaluation_id)
    specs = build_mistake_specs(context)
    result = service.rpc("replace_handwritten_mistakes", {
        "p_tenant": tenant_id, "p_evaluation": evaluation_id, "p_rows": specs,
    }).execute()
    if result.data is None:
        raise RuntimeError("Mistake replacement did not complete.")
    return context


def reconcile_revision_items(service, *, tenant_id: str, student_id: str,
                             subject_id: str) -> None:
    result = service.rpc("reconcile_handwritten_revision_items", {
        "p_tenant": tenant_id, "p_student": student_id, "p_subject": subject_id,
    }).execute()
    if not result.data:
        raise RuntimeError("Revision reconciliation was not authorized.")


def _level(average: float) -> str:
    if average >= 80:
        return "exam_ready"
    if average >= 65:
        return "advanced"
    if average >= 50:
        return "proficient"
    if average >= 35:
        return "improving"
    return "beginner"


def analytics_values(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")))
    scores = [_number(row.get("percentage")) for row in ordered]
    average = sum(scores) / len(scores) if scores else 0.0
    differences = [scores[index] - scores[index - 1] for index in range(1, len(scores))]
    return {
        "total_attempts": len(scores), "avg_percentage": round(average, 2),
        "best_percentage": round(max(scores), 2) if scores else 0.0,
        "latest_percentage": round(scores[-1], 2) if scores else 0.0,
        "score_history": [{
            "evaluation_id": str(row["id"]), "percentage": round(_number(row.get("percentage")), 2),
            "date": str(row.get("created_at") or "")[:10],
        } for row in ordered],
        "current_level": _level(average),
        "improvement_rate": round(sum(differences) / len(differences), 2) if differences else 0.0,
    }


def update_student_analytics(service, *, tenant_id: str, student_id: str,
                             subject_id: str) -> dict:
    papers = select_all(
        service, "evaluation_papers", "id",
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("subject_id", subject_id),
    )
    paper_ids = [str(row["id"]) for row in papers]
    submissions = select_all_in(
        service, "handwritten_submissions", "id,evaluation_paper_id,created_at",
        in_column="evaluation_paper_id", values=paper_ids,
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("student_id", student_id)
        .eq("status", "evaluated"),
    )
    evaluations = select_all_in(
        service, "handwritten_evaluations", "id,submission_id,percentage,created_at",
        in_column="submission_id", values=[str(row["id"]) for row in submissions],
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("status", "completed"),
    )
    values = analytics_values(evaluations)
    service.table("handwritten_student_analytics").upsert({
        "tenant_id": tenant_id, "student_id": student_id, "subject_id": subject_id,
        **values,
    }, on_conflict="tenant_id,student_id,subject_id").execute()
    return values


def current_evaluation_ids(service, *, tenant_id: str, student_id: str,
                           subject_id: str | None = None,
                           subject_ids: set[str] | None = None) -> list[str]:
    papers = select_all(
        service, "evaluation_papers", "id,subject_id",
        configure=lambda query: query.eq("tenant_id", tenant_id),
    )
    if subject_id:
        papers = [row for row in papers if str(row.get("subject_id")) == subject_id]
    elif subject_ids is not None:
        papers = [row for row in papers if str(row.get("subject_id")) in subject_ids]
    paper_ids = {str(row["id"]) for row in papers}
    submissions = select_all(
        service, "handwritten_submissions", "id,evaluation_paper_id,created_at",
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("student_id", student_id)
        .eq("status", "evaluated"),
    )
    submissions = [row for row in submissions if str(row.get("evaluation_paper_id")) in paper_ids]
    by_submission = {str(row["id"]): row for row in submissions}
    evaluations = select_all_in(
        service, "handwritten_evaluations", "id,submission_id,created_at",
        in_column="submission_id", values=list(by_submission),
        configure=lambda query: query.eq("tenant_id", tenant_id).eq("status", "completed"),
    )
    latest: dict[str, tuple[tuple[str, str, str, str], dict]] = {}
    for row in evaluations:
        submission = by_submission.get(str(row.get("submission_id")))
        paper_id = str(submission.get("evaluation_paper_id")) if submission else None
        previous = latest.get(paper_id or "")
        rank = (str(submission.get("created_at") or ""), str(submission.get("id") or ""),
                str(row.get("created_at") or ""), str(row["id"])) if submission else ()
        if paper_id and (previous is None or rank > previous[0]):
            latest[paper_id] = (rank, row)
    return [str(value[1]["id"]) for value in latest.values()]


def current_mistakes(service, *, tenant_id: str, student_id: str,
                     subject_id: str | None = None, severity: str | None = None,
                     subject_ids: set[str] | None = None) -> list[dict]:
    evaluation_ids = current_evaluation_ids(
        service, tenant_id=tenant_id, student_id=student_id, subject_id=subject_id,
        subject_ids=subject_ids,
    )
    mistakes = select_all_in(
        service, "handwritten_mistakes",
        "id,evaluation_id,question_result_id,category,severity,description,marks_lost,"
        "suggestion,chapter_name,criterion_key,signature,is_recurring,created_at",
        in_column="evaluation_id", values=evaluation_ids,
        configure=lambda query: query.eq("tenant_id", tenant_id)
        if not severity else query.eq("tenant_id", tenant_id).eq("severity", severity),
        order_column="created_at", order_desc=True,
    )
    if not mistakes:
        return []

    evaluations = select_all_in(
        service,
        "handwritten_evaluations",
        "id,submission_id",
        in_column="id",
        values=[str(row["evaluation_id"]) for row in mistakes],
        configure=lambda query: query.eq("tenant_id", tenant_id),
    )
    evaluation_sources = {str(row["id"]): row for row in evaluations}
    submissions = select_all_in(
        service,
        "handwritten_submissions",
        "id,evaluation_paper_id",
        in_column="id",
        values=[str(row["submission_id"]) for row in evaluations],
        configure=lambda query: query.eq("tenant_id", tenant_id).eq(
            "student_id", student_id
        ),
    )
    submission_sources = {str(row["id"]): row for row in submissions}
    papers = select_all_in(
        service,
        "evaluation_papers",
        "id,subject_id,title",
        in_column="id",
        values=[str(row["evaluation_paper_id"]) for row in submissions],
        configure=lambda query: query.eq("tenant_id", tenant_id),
    )
    paper_sources = {str(row["id"]): row for row in papers}

    enriched: list[dict] = []
    for mistake in mistakes:
        evaluation = evaluation_sources.get(str(mistake["evaluation_id"]))
        submission_id = str(evaluation["submission_id"]) if evaluation else None
        submission = submission_sources.get(submission_id or "")
        paper = (
            paper_sources.get(str(submission["evaluation_paper_id"]))
            if submission
            else None
        )
        enriched.append({
            **mistake,
            "subject_id": paper.get("subject_id") if paper else None,
            "submission_id": submission_id,
            "paper_title": paper.get("title") if paper else None,
        })
    return enriched
