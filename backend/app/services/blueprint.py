"""
Blueprint-driven quiz generation (Slice 7).

The app (exam setter) turns the teacher's selected topics + High/Med/Low weights
into a concrete blueprint — how many questions per priority topic, plus a
"general" count for whole-document coverage. Gemini (question writer) then fills
that blueprint covering the whole document. Questions on a priority topic are
tagged with that topic's id; general questions are left untagged (topic_id NULL).
"""

from __future__ import annotations

from collections import Counter
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
from app.services.llm.structured import complete_json_with_fallback
from app.services.question_validation import validate_question_answer_shape
from app.services.teacher_access import teacher_has_subject

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
    weight: Weight = "medium"
    # New per-topic blueprint: the teacher sets exact per-format counts for this
    # topic (e.g. {"mcq_single": 2, "fill_blank": 1}). When present on any topic,
    # the weight math is bypassed entirely (see build_blueprint).
    counts: dict[str, int] | None = None


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
        validate_question_answer_shape(self.type, self.options, self.correct_answer)


class BPQuiz(BaseModel):
    questions: list[BPQuestion]


def build_blueprint(
    selected: list[SelectedTopic], total: int, *, selected_only: bool = False
) -> dict:
    """
    Turn selected topics + weights into per-topic counts + a general count.

    Whole-document coverage: priority topics share ~EMPHASIS_FRACTION of the
    total (split 3:2:1 by weight, each >= 1); the remainder is general coverage.
    With no selected topics, the whole quiz is general coverage.
    """
    if not selected:
        total = max(total, 1)
        return {"topics": [], "general": total, "total": total}

    # Per-topic explicit blueprint: each selected topic carries its own per-format
    # counts (the teacher set them directly). The quiz is built ONLY from these
    # topics — no High/Med/Low weight math and no general coverage. The total is
    # simply the sum of every topic's counts.
    if any(t.counts for t in selected):
        topics = []
        for t in selected:
            counts = {k: int(v) for k, v in (t.counts or {}).items() if v and v > 0}
            topics.append(
                {"name": t.name, "counts": counts, "num_questions": sum(counts.values())}
            )
        emphasis_total = sum(x["num_questions"] for x in topics)
        return {
            "topics": topics,
            "general": 0,
            "total": emphasis_total,
            "mode": "per_topic",
        }

    # Each selected topic must get at least one question. Never silently raise the
    # teacher's requested total: that would contradict the exact per-type mix.
    if len(selected) > total:
        raise ValueError(
            "The number of selected topics cannot exceed the requested question count."
        )
    emphasis_budget = (
        total
        if selected_only
        else min(total, max(len(selected), round(total * _EMPHASIS_FRACTION)))
    )

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


def _validated_generated_quiz(data: object, expected_counts: dict[str, int]) -> BPQuiz:
    """Validate shape and the teacher's exact requested type distribution."""
    try:
        quiz = BPQuiz.model_validate(data)
    except ValidationError as exc:
        raise LLMError("Model returned invalid quiz JSON.") from exc
    if not quiz.questions:
        raise LLMError("Model returned no questions.")
    for question in quiz.questions:
        try:
            question.check_shape()
        except ValueError as exc:
            raise LLMError(f"Model produced a malformed question: {exc}") from exc

    actual = Counter(question.type for question in quiz.questions)
    expected = Counter(
        {kind: count for kind, count in expected_counts.items() if count > 0}
    )
    if actual != expected:
        expected_text = ", ".join(
            f"{kind}={count}" for kind, count in sorted(expected.items())
        )
        actual_text = (
            ", ".join(f"{kind}={count}" for kind, count in sorted(actual.items()))
            or "none"
        )
        raise LLMError(
            "AI question mix mismatch: "
            f"requested {sum(expected.values())} ({expected_text}); "
            f"received {sum(actual.values())} ({actual_text})."
        )
    return quiz


def _generate_with_exact_mix(
    system: str, user: str, expected_counts: dict[str, int]
) -> tuple[BPQuiz, str]:
    """Generate once, then make one explicit correction attempt for a bad mix."""
    data, provider = complete_json_with_fallback(system, user)
    try:
        return _validated_generated_quiz(data, expected_counts), provider
    except LLMError as first_error:
        if "question mix mismatch" not in str(first_error):
            raise

        expected_text = ", ".join(
            f"{kind}={count}"
            for kind, count in sorted(expected_counts.items())
            if count > 0
        )
        corrective_system = (
            system
            + "\n\nCORRECTION REQUIRED: Your previous response did not match the exact "
            f"question-type distribution. Return exactly: {expected_text}. Rebuild the "
            "complete JSON response and obey every original grounding rule."
        )
        corrected, corrected_provider = complete_json_with_fallback(
            corrective_system, user
        )
        return _validated_generated_quiz(corrected, expected_counts), corrected_provider


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

    # 0) Explicit assignments are authoritative. Course enrolment is maintained
    # as derived compatibility data and must never grant additional access.
    if not teacher_has_subject(service, profile, subject_id):
        raise ValueError("Subject not found.")

    # 1) Fetch the document + extract text.
    doc = (
        service.table("documents").select("storage_path,file_type")
        .eq("id", document_id)
        .eq("tenant_id", tid)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    text = extract_text(download_bytes(doc.data["storage_path"]), doc.data["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    material = text[: get_settings().generation_max_text_chars]

    # 2) Generate + persist from the document's own text. (For LARGE documents the
    #    caller uses generate_and_persist_from_material directly with a Master
    #    Blueprint as the material instead — same writer + persistence.)
    return generate_and_persist_from_material(
        service=service,
        tenant_id=tid,
        material=material,
        subject_id=subject_id,
        chapter_name=chapter_name,
        selected_topics=selected_topics,
        total_questions=total_questions,
        question_types=question_types,
        cognitive_level=cognitive_level,
        difficulty=difficulty,
        profile=profile,
        type_counts=type_counts,
        source_document_id=document_id,
    )


def generate_and_persist_from_material(
    *,
    service,
    tenant_id: str,
    material: str,
    subject_id: str,
    chapter_name: str,
    selected_topics: list[dict],
    total_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    profile: CurrentProfile,
    type_counts: dict[str, int] | None = None,
    selected_only_material: bool = False,
    source_document_id: str | None = None,
) -> dict:
    """Write + persist a blueprint-driven quiz from a block of `material`.

    `material` is either a small document's raw text (single-pass path) or a
    consolidated Master Blueprint rendered to text (large-document path). For
    the latter, `selected_only_material=True` tells allocation and prompting
    that no whole-document/general coverage is available or desired.
    """
    tid = tenant_id
    chapter_name = chapter_name.strip()

    # Build the blueprint (exam setter).
    selected = [SelectedTopic(**t) for t in selected_topics]
    # A per-topic blueprint (each topic carries its own counts) is inherently
    # selected-topics-only: there is no general/whole-document coverage.
    per_topic = any(t.counts for t in selected)
    selected_only = selected_only_material or per_topic
    blueprint = build_blueprint(selected, total_questions, selected_only=selected_only)

    # Generate (question writer) with Gemini primary and DeepSeek fallback.
    system = build_blueprint_system_prompt(
        question_types,
        cognitive_level,
        difficulty,
        selected_only_material=selected_only,
    )
    user = build_blueprint_user_prompt(
        material,
        blueprint,
        question_types,
        cognitive_level,
        difficulty,
        type_counts,
        selected_only_material=selected_only,
    )
    expected_counts = (
        {kind: count for kind, count in type_counts.items() if count > 0}
        if type_counts
        else {kind: 0 for kind in question_types}
    )
    if not type_counts:
        # The legacy caller specifies only a total and allowed types. Preserve that
        # path by validating total count, while exact per-type enforcement is used
        # by the teacher blueprint UI.
        data, provider = complete_json_with_fallback(system, user)
        try:
            quiz = BPQuiz.model_validate(data)
        except ValidationError as exc:
            raise LLMError("Model returned invalid quiz JSON.") from exc
        questions = quiz.questions
        if len(questions) != total_questions:
            raise LLMError(
                f"AI generated {len(questions)} questions instead of the requested "
                f"{total_questions}."
            )
        for q in questions:
            try:
                q.check_shape()
            except ValueError as exc:
                raise LLMError(f"Model produced a malformed question: {exc}") from exc
    else:
        quiz, provider = _generate_with_exact_mix(system, user, expected_counts)
        questions = quiz.questions

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
    quiz_set_values = {
        "tenant_id": tid, "chapter_id": chapter_id, "subject_id": subject_id,
        "title": f"{chapter_name} — {cognitive_level}",
        "status": "draft", "created_by": profile.user_id,
    }
    if source_document_id:
        quiz_set_values["document_id"] = source_document_id
    quiz_set = service.table("quiz_sets").insert(quiz_set_values).execute()
    quiz_set_id = quiz_set.data[0]["id"]

    stored: list[dict] = []
    created_question_ids: list[str] = []
    try:
        total_marks = sum(q.marks for q in questions)
        variant = service.table("quiz_variants").insert({
            "tenant_id": tid, "quiz_set_id": quiz_set_id,
            "variant_type": cognitive_level, "total_marks": total_marks,
        }).execute()
        variant_id = variant.data[0]["id"]

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
            created_question_ids.append(question_id)
            service.table("quiz_variant_questions").insert({
                "tenant_id": tid, "variant_id": variant_id,
                "question_id": question_id, "order_index": index,
            }).execute()
            stored.append({"id": question_id, **q.model_dump()})
    except Exception:
        service.table("quiz_sets").delete().eq("id", quiz_set_id).execute()
        if created_question_ids:
            service.table("questions").delete().in_("id", created_question_ids).execute()
        raise

    # Instrument: one 'question.generated' event per question (best-effort).
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
        "provider": provider,
        "blueprint": blueprint,
        "questions": stored,
    }
