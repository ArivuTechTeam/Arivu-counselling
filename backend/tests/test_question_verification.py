from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.question_verification import verify_generated_questions


MODULE = "app.services.question_verification"
EXCERPT = "The treaty was signed in Versailles on 28 June 1919."


def _question():
    return SimpleNamespace(
        type="mcq_single",
        question_text="Where was the treaty signed?",
        options=[
            {"id": "a", "text": "Versailles"},
            {"id": "b", "text": "London"},
        ],
        correct_answer="a",
        explanation="The source explicitly identifies Versailles as the signing location.",
        source_excerpt=EXCERPT,
        source_page_start=90,
        source_page_end=90,
        grounding_confidence=0.94,
    )


def test_complete_batch_uses_exactly_one_verifier_call() -> None:
    questions = [_question(), _question()]
    material = f"=== SOURCE PAGE 90 ===\n{EXCERPT}"
    with patch(
        f"{MODULE}.complete_json_with_fallback",
        return_value=(
            {"questions": [
                {"index": 0, "status": "verified", "warnings": []},
                {"index": 1, "status": "ambiguous", "warnings": ["Wording overlaps."]},
            ]},
            "gemini",
        ),
    ) as complete:
        checks = verify_generated_questions(questions, material)

    assert complete.call_count == 1
    # Deterministic duplicate blocking remains authoritative over a softer AI result.
    assert checks[0].status == "unsupported"
    assert checks[1].status == "unsupported"


def test_incomplete_verifier_response_fails_safe_to_teacher_review() -> None:
    material = f"=== SOURCE PAGE 90 ===\n{EXCERPT}"
    with patch(
        f"{MODULE}.complete_json_with_fallback",
        return_value=({"questions": []}, "gemini"),
    ):
        check = verify_generated_questions([_question()], material)[0]

    assert check.status == "needs_teacher_review"
    assert any("verification was unavailable" in warning for warning in check.warnings)
