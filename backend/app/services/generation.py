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
from app.services.extraction import ExtractedText, extract_text_with_pages
from app.services.llm import LLMError, complete_with_fallback
from app.services.ai_call_logging import ai_call_context
from app.services.quiz_prompts import build_system_prompt, build_user_prompt
from app.services.question_validation import (
    validate_question_answer_shape,
    validate_question_presentation,
)
from app.services.question_verification import verify_generated_questions
from app.services.source_material import render_extracted_material
from app.services.teacher_access import teacher_has_subject

# For long documents we skip likely front-matter (cover, copyright page, table
# of contents, preface) and then take a large slice of real subject content — so
# questions come from concepts, not the book's metadata. Window size is tunable
# via GENERATION_MAX_TEXT_CHARS. Chapter-scoped selection is a later improvement.
_FRONT_MATTER_SKIP_FRACTION = 0.08
_FRONT_MATTER_MIN_DOC_CHARS = 20000


def _select_material(extracted: ExtractedText) -> str:
    max_chars = get_settings().generation_max_text_chars
    # Only skip front-matter on genuinely long docs; short notes are used whole.
    start = (
        int(len(extracted.text) * _FRONT_MATTER_SKIP_FRACTION)
        if len(extracted.text) > _FRONT_MATTER_MIN_DOC_CHARS
        else 0
    )
    return render_extracted_material(extracted, start=start, max_chars=max_chars)

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
    source_excerpt: str = ""
    source_page_start: int | None = None
    source_page_end: int | None = None
    grounding_confidence: float = 0

    def check_shape(self) -> None:
        """Reject output that cannot be graded deterministically."""
        validate_question_answer_shape(self.type, self.options, self.correct_answer)


class GeneratedQuiz(BaseModel):
    questions: list[GeneratedQuestion]


def _parse_and_validate_generated_quiz(
    raw: str, num_questions: int, requested_difficulty: str
) -> list[GeneratedQuestion]:
    try:
        quiz = GeneratedQuiz.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError("Model returned invalid quiz JSON.") from exc

    questions = quiz.questions[:num_questions]
    if not questions:
        raise LLMError("Model returned no questions.")
    for question in questions:
        try:
            question.check_shape()
            validate_question_presentation(
                question_type=question.type,
                question_text=question.question_text,
                explanation=question.explanation,
                source_excerpt=question.source_excerpt,
                requested_difficulty=requested_difficulty,
                declared_difficulty=question.difficulty,
            )
        except ValueError as exc:
            raise LLMError(f"Model produced an unsuitable question: {exc}") from exc
    return questions


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

    # 0) Explicit assignments are authoritative. Course enrolment is maintained
    # as derived compatibility data and must never grant additional access.
    if subject_id and not teacher_has_subject(service, profile, subject_id):
        raise ValueError("Subject not found.")

    # 1) Fetch the document, scoped to the caller's tenant.
    doc = (
        service.table("documents")
        .select("storage_path,file_type,chapter_id,original_filename")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    doc_row = doc.data

    # 2) Re-extract text from the stored original.
    content = download_bytes(doc_row["storage_path"])
    extracted = extract_text_with_pages(content, doc_row["file_type"])
    if not extracted.text.strip():
        raise ValueError("This document has no extractable text (scanned PDF?).")
    material = _select_material(extracted)

    # 3) Build prompts and call the configured Gemini primary / DeepSeek fallback.
    system = build_system_prompt(question_types, cognitive_level, difficulty)
    user = build_user_prompt(
        material, num_questions, question_types, cognitive_level, difficulty
    )
    with ai_call_context(
        "quiz_generation", tenant_id=profile.tenant_id, document_id=document_id
    ):
        raw, provider = complete_with_fallback(system, user)

    # 4) Validate the model's JSON and student-facing wording. If the provider
    # violates a presentation rule, give it one explicit rewrite opportunity;
    # never persist a formula giveaway or document-reference question.
    try:
        questions = _parse_and_validate_generated_quiz(
            raw, num_questions, difficulty
        )
    except LLMError as first_error:
        corrective_system = (
            system
            + "\n\nCORRECTION REQUIRED: Rewrite the complete quiz. No question stem "
            "may reveal its answer-bearing formula/rule, and no question or "
            "explanation may refer to a handbook, document, PDF, source material, "
            "notes, passage, page, or uploaded file. Preserve the requested "
            f"{difficulty} difficulty and all original JSON/type rules."
        )
        with ai_call_context(
            "quiz_generation", tenant_id=profile.tenant_id, document_id=document_id
        ):
            corrected_raw, corrected_provider = complete_with_fallback(
                corrective_system, user
            )
        try:
            questions = _parse_and_validate_generated_quiz(
                corrected_raw, num_questions, difficulty
            )
        except LLMError:
            raise first_error
        provider = corrected_provider
    with ai_call_context(
        "question_verification", tenant_id=profile.tenant_id, document_id=document_id
    ):
        verification = verify_generated_questions(questions, material)

    # 5) Store: quiz_set -> variant -> questions (all pending review).
    quiz_set = (
        service.table("quiz_sets")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "chapter_id": doc_row.get("chapter_id"),
                "subject_id": subject_id,
                "document_id": document_id,  # link back to the source upload
                "title": f"{doc_row.get('original_filename', 'Quiz')} — {cognitive_level}",
                "status": "draft",
                "created_by": profile.user_id,
            }
        )
        .execute()
    )
    quiz_set_id = quiz_set.data[0]["id"]

    stored: list[dict] = []
    created_question_ids: list[str] = []
    try:
        total_marks = sum(q.marks for q in questions)
        variant = (
            service.table("quiz_variants")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "quiz_set_id": quiz_set_id,
                    "variant_type": cognitive_level,
                    "total_marks": total_marks,
                }
            )
            .execute()
        )
        variant_id = variant.data[0]["id"]

        for index, q in enumerate(questions):
            verified = verification[index]
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
                        "source_excerpt": q.source_excerpt,
                        "source_page_start": q.source_page_start,
                        "source_page_end": q.source_page_end,
                        "grounding_confidence": q.grounding_confidence,
                        "verification_status": verified.status,
                        "verification_warnings": verified.warnings,
                        "source": "ai_generated",
                        "review_status": "pending_review",
                        "created_by": profile.user_id,
                    }
                )
                .execute()
            )
            question_id = question_row.data[0]["id"]
            created_question_ids.append(question_id)
            service.table("quiz_variant_questions").insert(
                {
                    "tenant_id": profile.tenant_id,
                    "variant_id": variant_id,
                    "question_id": question_id,
                    "order_index": index,
                }
            ).execute()
            stored.append({
                "id": question_id,
                **q.model_dump(),
                "verification_status": verified.status,
                "verification_warnings": verified.warnings,
            })
    except Exception:
        # Compensate across PostgREST calls so failed generations do not leave
        # visible draft sets or orphaned questions.
        service.table("quiz_sets").delete().eq("id", quiz_set_id).eq(
            "tenant_id", profile.tenant_id
        ).eq("created_by", profile.user_id).execute()
        if created_question_ids:
            service.table("questions").delete().in_("id", created_question_ids).eq(
                "tenant_id", profile.tenant_id
            ).eq("created_by", profile.user_id).execute()
        raise

    return {
        "quiz_set_id": quiz_set_id,
        "variant_id": variant_id,
        "provider": provider,
        "questions": stored,
    }
