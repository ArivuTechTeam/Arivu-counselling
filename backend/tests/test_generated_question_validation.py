from __future__ import annotations

import pytest

from app.services.blueprint import BPQuestion
from app.services.generation import GeneratedQuestion


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
