from __future__ import annotations

import pytest

from app.services.blueprint import BPQuestion
from app.services.generation import GeneratedQuestion
from app.services.question_validation import validate_question_presentation


QUESTION_CLASSES = (GeneratedQuestion, BPQuestion)
OPTIONS = [{"id": "a", "text": "Alpha"}, {"id": "b", "text": "Beta"}]


@pytest.mark.parametrize("question_class", QUESTION_CLASSES)
@pytest.mark.parametrize(
    ("question_type", "options", "correct_answer"),
    [
        ("mcq_single", OPTIONS, "a"),
        ("mcq_multi", OPTIONS, ["a", "b"]),
        (
            "true_false",
            [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
            "true",
        ),
        ("numerical", None, {"value": 10, "tolerance": 0.1}),
        ("fill_blank", None, {"answers": ["net profit", "profit"]}),
    ],
)
def test_valid_gradeable_shapes_are_accepted(
    question_class, question_type, options, correct_answer
) -> None:
    question = question_class(
        type=question_type,
        question_text="Question",
        options=options,
        correct_answer=correct_answer,
    )
    question.check_shape()


@pytest.mark.parametrize("question_class", QUESTION_CLASSES)
@pytest.mark.parametrize(
    ("question_type", "options", "correct_answer", "message"),
    [
        ("mcq_single", OPTIONS, "missing", "match an option id"),
        ("mcq_multi", OPTIONS, ["a", "missing"], "match option ids"),
        ("mcq_multi", OPTIONS, [], "non-empty list"),
        ("numerical", None, {"tolerance": 0}, "value and tolerance"),
        ("numerical", None, {"value": 10, "tolerance": -1}, "non-negative"),
        ("fill_blank", None, {"answers": []}, "non-empty string list"),
        ("fill_blank", None, {"answers": [""]}, "non-empty string list"),
    ],
)
def test_malformed_gradeable_shapes_are_rejected(
    question_class, question_type, options, correct_answer, message
) -> None:
    question = question_class(
        type=question_type,
        question_text="Question",
        options=options,
        correct_answer=correct_answer,
    )
    with pytest.raises(ValueError, match=message):
        question.check_shape()


@pytest.mark.parametrize(
    ("question_text", "source_excerpt"),
    [
        (
            "According to the provided handbook, electrical power is P = I²R.",
            "P = VI = I²R",
        ),
        (
            "A resistor carries 4 A. Using the formula P = I²R, calculate its power.",
            "P = VI = I²R",
        ),
        (
            "The kinematics relationship is v² = u² - 2as. True or false?",
            "v² = u² + 2as",
        ),
    ],
)
def test_student_question_rejects_source_references_and_formula_giveaways(
    question_text: str,
    source_excerpt: str,
) -> None:
    with pytest.raises(ValueError):
        validate_question_presentation(
            question_type="true_false",
            question_text=question_text,
            explanation="Apply the relevant relationship to determine the result.",
            source_excerpt=source_excerpt,
            requested_difficulty="hard",
            declared_difficulty="hard",
        )


def test_standalone_application_keeps_formula_for_post_answer_explanation() -> None:
    validate_question_presentation(
        question_type="numerical",
        question_text=(
            "A resistor of 5 ohms carries a current of 4 amperes. "
            "Calculate the power dissipated."
        ),
        explanation="Power is I²R, so 4² × 5 gives 80 watts.",
        source_excerpt="P = VI = I²R",
        requested_difficulty="hard",
        declared_difficulty="hard",
    )


def test_explanation_must_not_refer_to_teacher_material() -> None:
    with pytest.raises(ValueError, match="explanation"):
        validate_question_presentation(
            question_type="mcq_single",
            question_text="Which relationship describes electrical power?",
            explanation="The handbook lists the correct relationship.",
            source_excerpt="P = VI = I²R",
        )


def test_requested_difficulty_must_be_preserved() -> None:
    with pytest.raises(ValueError, match="difficulty must be hard"):
        validate_question_presentation(
            question_type="numerical",
            question_text="Calculate the power dissipated by the resistor.",
            explanation="Apply the electrical power relationship.",
            source_excerpt="P = VI = I²R",
            requested_difficulty="hard",
            declared_difficulty="medium",
        )


def test_programming_question_may_include_code_needed_for_analysis() -> None:
    validate_question_presentation(
        question_type="mcq_single",
        question_text="Given `def add(x, y): return x + y`, what does add(2, 3) return?",
        explanation="The function returns the sum of its two arguments.",
        source_excerpt="def add(x, y): return x + y",
        requested_difficulty="medium",
        declared_difficulty="medium",
    )
