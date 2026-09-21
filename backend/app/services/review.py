"""
Teacher-review helpers (Slice 4).

get_quiz_set_detail  — assemble a quiz set with its variant(s) and each
                       variant's questions (in order) for the review screen.
regenerate_question  — ask the LLM to rewrite one question (same type/concept)
                       and replace it in place, back to pending_review.
"""

from __future__ import annotations

from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text_with_pages
from app.services.generation import GeneratedQuiz
from app.services.llm import LLMError, complete_with_fallback
from app.services.ai_call_logging import ai_call_context
from app.services.quiz_generator_service import render_blueprint_material
from app.services.quiz_prompts import build_regen_system_prompt, build_regen_user_prompt
from app.services.question_verification import verify_generated_questions
from app.services.question_validation import validate_question_presentation
from app.services.source_material import render_extracted_material


class RegenerationSourceError(ValueError):
    """The question exists, but its original grounding material is unavailable."""


def get_quiz_set_detail(quiz_set_id: str, tenant_id: str) -> dict:
    service = get_service_client()

    qs = (
        service.table("quiz_sets")
        .select("id, title, status, created_at, published_at")
        .eq("id", quiz_set_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if qs is None or not qs.data:
        raise ValueError("Quiz set not found.")

    variants = (
        service.table("quiz_variants")
        .select("id, variant_type, total_marks")
        .eq("quiz_set_id", quiz_set_id)
        .eq("tenant_id", tenant_id)
        .order("created_at")
        .execute()
        .data
        or []
    )

    out_variants = []
    for variant in variants:
        links = (
            service.table("quiz_variant_questions")
            .select("question_id, order_index")
            .eq("variant_id", variant["id"])
            .eq("tenant_id", tenant_id)
            .order("order_index")
            .execute()
            .data
            or []
        )
        question_ids = [link["question_id"] for link in links]
        questions = []
        if question_ids:
            rows = (
                service.table("questions")
                .select(
                    "id, type, question_text, options, correct_answer, explanation, "
                    "difficulty, marks, review_status, source_excerpt, "
                    "source_page_start, source_page_end, grounding_confidence, "
                    "verification_status, verification_warnings"
                )
                .in_("id", question_ids)
                .eq("tenant_id", tenant_id)
                .execute()
                .data
                or []
            )
            by_id = {row["id"]: row for row in rows}
            # Preserve the variant's question order.
            questions = [
                by_id[link["question_id"]]
                for link in links
                if link["question_id"] in by_id
            ]
        out_variants.append({**variant, "questions": questions})

    return {**qs.data, "variants": out_variants}


def _question_source_material(service, question: dict, tenant_id: str) -> str:
    """Recover the material used to create a question, tenant-scoped throughout."""
    link = (
        service.table("quiz_variant_questions")
        .select("variant_id")
        .eq("question_id", question["id"])
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not link or not link.data:
        raise RegenerationSourceError("Question source quiz was not found.")
    variant = (
        service.table("quiz_variants")
        .select("quiz_set_id")
        .eq("id", link.data["variant_id"])
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not variant or not variant.data:
        raise RegenerationSourceError("Question source quiz was not found.")
    quiz_set_id = variant.data["quiz_set_id"]

    # Large-document generation stores the consolidated source plus the exact
    # teacher selection. Re-render precisely that selection for regeneration.
    job = (
        service.table("quiz_generation_jobs")
        .select("master_blueprint,params")
        .eq("quiz_set_id", quiz_set_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if job and job.data and job.data.get("master_blueprint"):
        selected = (job.data.get("params") or {}).get("selected_topics") or []
        selected_names = {
            str(topic.get("name") or "").strip().casefold()
            for topic in selected
            if str(topic.get("name") or "").strip()
        }
        if not selected_names and question.get("topic_id"):
            topic = (
                service.table("topics")
                .select("name")
                .eq("id", question["topic_id"])
                .eq("tenant_id", tenant_id)
                .maybe_single()
                .execute()
            )
            if topic and topic.data and topic.data.get("name"):
                selected_names = {str(topic.data["name"]).strip().casefold()}
        material = render_blueprint_material(
            job.data["master_blueprint"], selected_names or None
        )
    else:
        quiz_set = (
            service.table("quiz_sets")
            .select("document_id")
            .eq("id", quiz_set_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        document_id = quiz_set.data.get("document_id") if quiz_set and quiz_set.data else None
        if not document_id:
            raise RegenerationSourceError(
                "This quiz has no linked source document for regeneration."
            )
        document = (
            service.table("documents")
            .select("storage_path,file_type")
            .eq("id", document_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        if not document or not document.data:
            raise RegenerationSourceError("Question source document was not found.")
        material = render_extracted_material(
            extract_text_with_pages(
                download_bytes(document.data["storage_path"]),
                document.data["file_type"],
            )
        )

    material = material.strip()
    if not material:
        raise RegenerationSourceError("Question source material is empty.")
    ceiling = get_settings().generation_max_text_chars
    if len(material) > ceiling:
        raise RegenerationSourceError(
            "Question source material is too large to regenerate safely."
        )
    return material


def regenerate_question(question_id: str, tenant_id: str) -> dict:
    service = get_service_client()

    row = (
        service.table("questions")
        .select(
            "id,type,question_text,options,correct_answer,explanation,difficulty,"
            "marks,topic_id"
        )
        .eq("id", question_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if row is None or not row.data:
        raise ValueError("Question not found.")
    existing = row.data
    source_material = _question_source_material(service, existing, tenant_id)

    system = build_regen_system_prompt(
        existing["type"], existing.get("difficulty") or "medium"
    )
    user = build_regen_user_prompt(existing, source_material)
    with ai_call_context("question_regeneration", tenant_id=tenant_id):
        raw, _provider = complete_with_fallback(
            system,
            user,
            preferred_provider=getattr(
                get_settings(), "question_regeneration_provider", "deepseek"
            ),
        )

    quiz = GeneratedQuiz.model_validate_json(raw)
    if not quiz.questions:
        raise LLMError("Regeneration returned no question.")
    new_q = quiz.questions[0]
    new_q.check_shape()
    if new_q.type != existing["type"]:
        raise LLMError("Regeneration changed the question type.")
    try:
        validate_question_presentation(
            question_type=new_q.type,
            question_text=new_q.question_text,
            explanation=new_q.explanation,
            source_excerpt=new_q.source_excerpt,
            requested_difficulty=existing.get("difficulty") or "medium",
            declared_difficulty=new_q.difficulty,
        )
    except ValueError:
        corrective_system = (
            system
            + "\n\nCORRECTION REQUIRED: Rewrite the question again. The stem must not "
            "reveal the answer-bearing formula/rule. Neither the question nor its "
            "explanation may mention a handbook, document, PDF, source material, "
            "notes, passage, page, or uploaded file."
        )
        with ai_call_context("question_regeneration", tenant_id=tenant_id):
            corrected_raw, _provider = complete_with_fallback(
                corrective_system,
                user,
                preferred_provider=getattr(
                    get_settings(), "question_regeneration_provider", "deepseek"
                ),
            )
        corrected_quiz = GeneratedQuiz.model_validate_json(corrected_raw)
        if not corrected_quiz.questions:
            raise LLMError("Regeneration correction returned no question.")
        new_q = corrected_quiz.questions[0]
        new_q.check_shape()
        if new_q.type != existing["type"]:
            raise LLMError("Regeneration changed the question type.")
        try:
            validate_question_presentation(
                question_type=new_q.type,
                question_text=new_q.question_text,
                explanation=new_q.explanation,
                source_excerpt=new_q.source_excerpt,
                requested_difficulty=existing.get("difficulty") or "medium",
                declared_difficulty=new_q.difficulty,
            )
        except ValueError as exc:
            raise LLMError(f"Regeneration produced an unsuitable question: {exc}") from exc
    with ai_call_context("question_verification", tenant_id=tenant_id):
        verified = verify_generated_questions([new_q], source_material)[0]

    # Replace content, keep the same row + type, reset review state.
    updated = (
        service.table("questions")
        .update(
            {
                "question_text": new_q.question_text,
                "options": new_q.options,
                "correct_answer": new_q.correct_answer,
                "explanation": new_q.explanation,
                "difficulty": new_q.difficulty,
                "marks": new_q.marks,
                "source_excerpt": new_q.source_excerpt,
                "source_page_start": new_q.source_page_start,
                "source_page_end": new_q.source_page_end,
                "grounding_confidence": new_q.grounding_confidence,
                "verification_status": verified.status,
                "verification_warnings": verified.warnings,
                "review_status": "pending_review",
                "reviewed_by": None,
                "reviewed_at": None,
            }
        )
        .eq("id", question_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    return updated.data[0]
