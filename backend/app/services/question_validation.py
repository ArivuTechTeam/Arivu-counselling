"""Strict validation for AI-generated, deterministically graded questions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


_CHOICE_TYPES = {"mcq_single", "mcq_multi", "true_false"}


def _choice_ids(question_type: str, options: Any) -> set[str]:
    if not isinstance(options, list) or not options:
        raise ValueError(f"{question_type} requires options")

    option_ids: list[str] = []
    for option in options:
        if not isinstance(option, Mapping):
            raise ValueError(f"{question_type} options must be objects")
        option_id = option.get("id")
        option_text = option.get("text")
        if not isinstance(option_id, str) or not option_id.strip():
            raise ValueError(f"{question_type} option ids must be non-empty strings")
        if not isinstance(option_text, str) or not option_text.strip():
            raise ValueError(f"{question_type} option text must be non-empty")
        option_ids.append(option_id)

    if len(set(option_ids)) != len(option_ids):
        raise ValueError(f"{question_type} option ids must be unique")
    return set(option_ids)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"numerical {field} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"numerical {field} must be finite")
    return parsed


def validate_question_answer_shape(
    question_type: str,
    options: Any,
    correct_answer: Any,
) -> None:
    """Reject answer shapes that the deterministic grader cannot score safely."""
    if correct_answer is None:
        raise ValueError("missing correct_answer")

    if question_type in _CHOICE_TYPES:
        option_ids = _choice_ids(question_type, options)
        if question_type == "mcq_multi":
            if not isinstance(correct_answer, list) or not correct_answer:
                raise ValueError("mcq_multi correct_answer must be a non-empty list")
            if not all(isinstance(answer, str) for answer in correct_answer):
                raise ValueError("mcq_multi correct answers must be option ids")
            if len(set(correct_answer)) != len(correct_answer):
                raise ValueError("mcq_multi correct answers must be unique")
            if not set(correct_answer).issubset(option_ids):
                raise ValueError("mcq_multi correct answers must match option ids")
            return

        if not isinstance(correct_answer, str) or correct_answer not in option_ids:
            raise ValueError(
                f"{question_type} correct_answer must match an option id"
            )
        return

    if options is not None:
        raise ValueError(f"{question_type} must not include options")

    if question_type == "numerical":
        if not isinstance(correct_answer, Mapping):
            raise ValueError("numerical correct_answer must be an object")
        if "value" not in correct_answer or "tolerance" not in correct_answer:
            raise ValueError("numerical correct_answer requires value and tolerance")
        _finite_number(correct_answer["value"], "value")
        tolerance = _finite_number(correct_answer["tolerance"], "tolerance")
        if tolerance < 0:
            raise ValueError("numerical tolerance must be non-negative")
        return

    if question_type == "fill_blank":
        if not isinstance(correct_answer, Mapping):
            raise ValueError("fill_blank correct_answer must be an object")
        answers = correct_answer.get("answers")
        if (
            not isinstance(answers, list)
            or not answers
            or not all(isinstance(answer, str) and answer.strip() for answer in answers)
        ):
            raise ValueError("fill_blank answers must be a non-empty string list")
        return

    raise ValueError(f"unsupported question type: {question_type}")
