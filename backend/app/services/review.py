"""
Teacher-review helpers (Slice 4).

get_quiz_set_detail  — assemble a quiz set with its variant(s) and each
                       variant's questions (in order) for the review screen.
regenerate_question  — ask the LLM to rewrite one question (same type/concept)
                       and replace it in place, back to pending_review.
"""

from __future__ import annotations

from app.lib.supabase import get_service_client
from app.services.generation import GeneratedQuiz
from app.services.llm import LLMError, complete_with_fallback
from app.services.quiz_prompts import build_regen_system_prompt, build_regen_user_prompt


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
                    "difficulty, marks, review_status"
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


def regenerate_question(question_id: str, tenant_id: str) -> dict:
    service = get_service_client()

    row = (
        service.table("questions")
        .select("*")
        .eq("id", question_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if row is None or not row.data:
        raise ValueError("Question not found.")
    existing = row.data

    system = build_regen_system_prompt(existing["type"])
    user = build_regen_user_prompt(existing)
    raw, _provider = complete_with_fallback(system, user)

    quiz = GeneratedQuiz.model_validate_json(raw)
    if not quiz.questions:
        raise LLMError("Regeneration returned no question.")
    new_q = quiz.questions[0]
    new_q.check_shape()

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
