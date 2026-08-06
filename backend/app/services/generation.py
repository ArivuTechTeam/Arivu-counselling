"""
Quiz generation orchestration.

Ties the pieces together:
  fetch document -> extract text -> build prompt -> call LLM (with fallback)
  -> validate JSON -> store quiz_set + variant + questions (pending review).

Raises ValueError for caller/input problems (bad document, empty text) and
LLMError for model problems (call failed, invalid JSON). The API layer maps
those to HTTP status codes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text
from app.services.llm import LLMError, complete_with_fallback
from app.services.quiz_prompts import build_system_prompt, build_user_prompt

# For long documents we skip likely front-matter (cover, copyright page, table
# of contents, preface) and then take a large slice of real subject content — so
# questions come from concepts, not the book's metadata. Window size is tunable
# via GENERATION_MAX_TEXT_CHARS. Chapter-scoped selection is a later improvement.
_FRONT_MATTER_SKIP_FRACTION = 0.08
_FRONT_MATTER_MIN_DOC_CHARS = 20000


def _select_material(text: str) -> str:
    max_chars = get_settings().generation_max_text_chars
    # Only skip front-matter on genuinely long docs; short notes are used whole.
    start = (
        int(len(text) * _FRONT_MATTER_SKIP_FRACTION)
        if len(text) > _FRONT_MATTER_MIN_DOC_CHARS
        else 0
    )
    return text[start : start + max_chars]

QuestionType = Literal[
    "mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank"
]


class GeneratedQuestion(BaseModel):
    type: QuestionType
    question_text: str
    options: list[dict] | None = None
    correct_answer: Any
    explanation: str | None = None
    difficulty: str = "medium"
    marks: float = 1

    def check_shape(self) -> None:
        """Light sanity checks the LLM output must satisfy before we store it."""
        if self.correct_answer is None:
            raise ValueError("missing correct_answer")
        if self.type in {"mcq_single", "mcq_multi", "true_false"} and not self.options:
            raise ValueError(f"{self.type} requires options")


class GeneratedQuiz(BaseModel):
    questions: list[GeneratedQuestion]


def generate_quiz(
    *,
    document_id: str,
    num_questions: int,
    question_types: list[str],
    cognitive_level: str,
    difficulty: str,
    profile: CurrentProfile,
    subject_id: str | None = None,
) -> dict:
    service = get_service_client()

    # 0) If a subject was chosen, confirm it belongs to this tenant.
    if subject_id:
        subj = (
            service.table("subjects")
            .select("id")
            .eq("id", subject_id)
            .eq("tenant_id", profile.tenant_id)
            .maybe_single()
            .execute()
        )
        if subj is None or not subj.data:
            raise ValueError("Subject not found.")

    # 1) Fetch the document, scoped to the caller's tenant.
    doc = (
        service.table("documents")
        .select("*")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    doc_row = doc.data

    # 2) Re-extract text from the stored original.
    content = download_bytes(doc_row["storage_path"])
    text = extract_text(content, doc_row["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned PDF?).")
    material = _select_material(text)

    # 3) Build prompts and call the model (DeepSeek, with fallback slot).
    system = build_system_prompt(question_types, cognitive_level, difficulty)
    user = build_user_prompt(
        material, num_questions, question_types, cognitive_level, difficulty
    )
    raw, provider = complete_with_fallback(system, user)

    # 4) Validate the model's JSON.
    try:
        quiz = GeneratedQuiz.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(f"Model returned invalid quiz JSON: {exc}") from exc

    questions = quiz.questions[:num_questions]
    if not questions:
        raise LLMError("Model returned no questions.")
    for q in questions:
        try:
            q.check_shape()
        except ValueError as exc:
            raise LLMError(f"Model produced a malformed question: {exc}") from exc

    # 5) Store: quiz_set -> variant -> questions (all pending review).
    quiz_set = (
        service.table("quiz_sets")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "chapter_id": doc_row.get("chapter_id"),
                "subject_id": subject_id,
                "title": f"{doc_row.get('original_filename', 'Quiz')} — {cognitive_level}",
                "status": "draft",
                "created_by": profile.user_id,
            }
        )
        .execute()
    )
    quiz_set_id = quiz_set.data[0]["id"]

    total_marks = sum(q.marks for q in questions)
    variant = (
        service.table("quiz_variants")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "quiz_set_id": quiz_set_id,
                "variant_type": cognitive_level,  # theory | practical | mixed
                "total_marks": total_marks,
            }
        )
        .execute()
    )
    variant_id = variant.data[0]["id"]

    stored: list[dict] = []
    for index, q in enumerate(questions):
        question_row = (
            service.table("questions")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "chapter_id": doc_row.get("chapter_id"),
                    "type": q.type,
                    "question_text": q.question_text,
                    "options": q.options,
                    "correct_answer": q.correct_answer,
                    "explanation": q.explanation,
                    "difficulty": q.difficulty,
                    "marks": q.marks,
                    "source": "ai_generated",
                    "review_status": "pending_review",
                    "created_by": profile.user_id,
                }
            )
            .execute()
        )
        question_id = question_row.data[0]["id"]
        service.table("quiz_variant_questions").insert(
            {
                "tenant_id": profile.tenant_id,
                "variant_id": variant_id,
                "question_id": question_id,
                "order_index": index,
            }
        ).execute()
        stored.append({"id": question_id, **q.model_dump()})

    return {
        "quiz_set_id": quiz_set_id,
        "variant_id": variant_id,
        "provider": provider,
        "questions": stored,
    }
