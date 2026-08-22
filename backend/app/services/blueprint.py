"""
Blueprint-driven quiz generation (Slice 7).

The app (exam setter) turns the teacher's selected topics + High/Med/Low weights
into a concrete blueprint — how many questions per priority topic, plus a
"general" count for whole-document coverage. Gemini (question writer) then fills
that blueprint covering the whole document. Questions on a priority topic are
tagged with that topic's id; general questions are left untagged (topic_id NULL).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.blueprint_prompts import (
    GENERAL_TOPIC,
    build_blueprint_system_prompt,
    build_blueprint_user_prompt,
)
from app.services.events import QUESTION_GENERATED, log_events, make_event
from app.services.extraction import extract_text
from app.services.llm.base import LLMError
from app.services.llm.structured import gemini_json

QuestionType = Literal[
    "mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"
]
Weight = Literal["high", "medium", "low"]

_WEIGHT_UNITS = {"high": 3, "medium": 2, "low": 1}
# Share of the quiz devoted to the selected priority topics; the remainder
# covers the rest of the document. Tunable without touching the flow.
_EMPHASIS_FRACTION = 0.7


class SelectedTopic(BaseModel):
    name: str
    weight: Weight


class BPQuestion(BaseModel):
    topic: str | None = None
    type: QuestionType
    question_text: str
    options: list[dict] | None = None
    correct_answer: Any
    explanation: str | None = None
    difficulty: str = "medium"
    marks: float = 1

    def check_shape(self) -> None:
        if self.correct_answer is None:
            raise ValueError("missing correct_answer")
        if self.type in {"mcq_single", "mcq_multi", "true_false"} and not self.options:
            raise ValueError(f"{self.type} requires options")


class BPQuiz(BaseModel):
    questions: list[BPQuestion]


def build_blueprint(selected: list[SelectedTopic], total: int) -> dict:
    """
    Turn selected topics + weights into per-topic counts + a general count.

    Whole-document coverage: priority topics share ~EMPHASIS_FRACTION of the
    total (split 3:2:1 by weight, each >= 1); the remainder is general coverage.
    With no selected topics, the whole quiz is general coverage.
    """
    if not selected:
        total = max(total, 1)
        return {"topics": [], "general": total, "total": total}

    # Each selected topic must get at least 1 → total can't be below topic count.
    total = max(total, len(selected))
    emphasis_budget = min(total, max(len(selected), round(total * _EMPHASIS_FRACTION)))

    units = [_WEIGHT_UNITS[t.weight] for t in selected]
    unit_sum = sum(units)
    counts = [max(1, round(emphasis_budget * u / unit_sum)) for u in units]

    # Trim rounding overflow so emphasis never exceeds the total (keep each >= 1).
    while sum(counts) > total:
        i = counts.index(max(counts))
        if counts[i] <= 1:
            break
        counts[i] -= 1

    emphasis_total = sum(counts)
    general = max(0, total - emphasis_total)
    topics = [
        {"name": t.name, "weight": t.weight, "num_questions": c}
        for t, c in zip(selected, counts)
    ]
    return {"topics": topics, "general": general, "total": emphasis_total + general}


def _get_or_create(service, table: str, tenant_id: str, match: dict, insert: dict) -> str:
    """Return the id of a row matching `match`, creating it from `insert` if none."""
    q = service.table(table).select("id").eq("tenant_id", tenant_id)
    for k, v in match.items():
        q = q.eq(k, v)
    rows = q.limit(1).execute().data or []
    if rows:
        return rows[0]["id"]
    created = service.table(table).insert({"tenant_id": tenant_id, **insert}).execute()
    return created.data[0]["id"]


def generate_blueprint_quiz(
    *,
    document_id: str,
    subject_id: str,
    chapter_name: str,
    selected_topics: list[dict],
    total_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    profile: CurrentProfile,
    type_counts: dict[str, int] | None = None,
) -> dict:
    service = get_service_client()
    tid = profile.tenant_id
    chapter_name = chapter_name.strip()

    # 0) Subject must belong to this tenant.
    subj = (
        service.table("subjects").select("id")
        .eq("id", subject_id).eq("tenant_id", tid).maybe_single().execute()
    )
    if subj is None or not subj.data:
        raise ValueError("Subject not found.")

    # 1) Fetch the document + extract text.
    doc = (
        service.table("documents").select("*")
        .eq("id", document_id).eq("tenant_id", tid).maybe_single().execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    text = extract_text(download_bytes(doc.data["storage_path"]), doc.data["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    material = text[: get_settings().generation_max_text_chars]

    # 2) Build the blueprint (exam setter).
    selected = [SelectedTopic(**t) for t in selected_topics]
    blueprint = build_blueprint(selected, total_questions)

    # 3) Generate (question writer) — Flash-Lite, JSON out, whole-doc coverage.
    system = build_blueprint_system_prompt(question_types, cognitive_level, difficulty)
    user = build_blueprint_user_prompt(
        material, blueprint, question_types, cognitive_level, difficulty, type_counts
    )
    data = gemini_json(
        system, user, model=get_settings().gemini_blueprint_model, temperature=0.3
    )
    try:
        quiz = BPQuiz.model_validate(data)
    except ValidationError as exc:
        raise LLMError(f"Model returned invalid quiz JSON: {exc}") from exc
    questions = quiz.questions
    if not questions:
        raise LLMError("Model returned no questions.")
    for q in questions:
        try:
            q.check_shape()
        except ValueError as exc:
            raise LLMError(f"Model produced a malformed question: {exc}") from exc

    # 4) Persist chapter + selected topics (exam-setter data; powers analytics).
    chapter_id = _get_or_create(
        service, "chapters", tid,
        {"subject_id": subject_id, "name": chapter_name},
        {"subject_id": subject_id, "name": chapter_name},
    )
    topic_id_by_name: dict[str, str] = {}
    for t in selected:
        name = t.name.strip()
        topic_id_by_name[name.lower()] = _get_or_create(
            service, "topics", tid,
            {"chapter_id": chapter_id, "name": name},
            {"chapter_id": chapter_id, "name": name},
        )

    # 5) quiz_set -> variant -> questions (all pending review).
    quiz_set = service.table("quiz_sets").insert({
        "tenant_id": tid, "chapter_id": chapter_id, "subject_id": subject_id,
        "title": f"{chapter_name} — {cognitive_level}",
        "status": "draft", "created_by": profile.user_id,
    }).execute()
    quiz_set_id = quiz_set.data[0]["id"]

    total_marks = sum(q.marks for q in questions)
    variant = service.table("quiz_variants").insert({
        "tenant_id": tid, "quiz_set_id": quiz_set_id,
        "variant_type": cognitive_level, "total_marks": total_marks,
    }).execute()
    variant_id = variant.data[0]["id"]

    stored: list[dict] = []
    for index, q in enumerate(questions):
        tag = (q.topic or "").strip().lower()
        topic_id = (
            None if tag in ("", GENERAL_TOPIC.lower()) else topic_id_by_name.get(tag)
        )
        qrow = service.table("questions").insert({
            "tenant_id": tid, "chapter_id": chapter_id, "topic_id": topic_id,
            "type": q.type, "question_text": q.question_text, "options": q.options,
            "correct_answer": q.correct_answer, "explanation": q.explanation,
            "difficulty": q.difficulty, "marks": q.marks,
            "source": "ai_generated", "review_status": "pending_review",
            "created_by": profile.user_id,
        }).execute()
        question_id = qrow.data[0]["id"]
        service.table("quiz_variant_questions").insert({
            "tenant_id": tid, "variant_id": variant_id,
            "question_id": question_id, "order_index": index,
        }).execute()
        stored.append({"id": question_id, **q.model_dump()})

    # Instrument: one 'question.generated' event per question (best-effort).
    provider = get_settings().gemini_blueprint_model
    log_events(
        [
            make_event(
                tenant_id=tid,
                event_type=QUESTION_GENERATED,
                actor_id=profile.user_id,
                actor_role=profile.role,
                subject_type="question",
                subject_id=s["id"],
                metadata={
                    "type": s.get("type"),
                    "difficulty": s.get("difficulty"),
                    "cognitive_level": cognitive_level,
                    "subject_id": subject_id,
                    "provider": provider,
                },
            )
            for s in stored
        ]
    )

    return {
        "quiz_set_id": quiz_set_id,
        "variant_id": variant_id,
        "provider": get_settings().gemini_blueprint_model,
        "blueprint": blueprint,
        "questions": stored,
    }
