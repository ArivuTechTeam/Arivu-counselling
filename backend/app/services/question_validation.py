"""Strict validation for AI-generated, deterministically graded questions."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from app.services.source_material import (
    is_symbolic_evidence,
    normalise_symbolic_evidence,
)


_CHOICE_TYPES = {"mcq_single", "mcq_multi", "true_false"}

_DOCUMENT_REFERENCE = re.compile(
    r"(?:"
    r"\baccording\s+to\s+(?:the\s+)?(?:provided\s+|uploaded\s+|given\s+)?"
    r"(?:handbook|document|material|text|pdf|notes?|passage|file|book|textbook|slides?|chapter|content)\b|"
    r"\bas\s+per\s+(?:the\s+)?(?:provided\s+|uploaded\s+|given\s+)?"
    r"(?:handbook|document|material|text|pdf|notes?|passage|file|book|textbook|slides?|chapter|content)\b|"
    r"\bas\s+(?:stated|given|mentioned|described|shown|presented|listed|explained)\s+in\s+"
    r"(?:the\s+)?(?:provided\s+|uploaded\s+|given\s+)?"
    r"(?:handbook|document|material|text|pdf|notes?|passage|file|book|textbook|slides?|chapter|content)\b|"
    r"\b(?:the\s+)?(?:provided\s+|uploaded\s+|given\s+)?"
    r"(?:handbook|document|file|book|textbook|slides?|chapter|content|source\s+material|provided\s+text|uploaded\s+notes?)\s+"
    r"(?:states?|lists?|says?|shows?|mentions?|describes?|provides?|explains?)\b|"
    r"\b(?:from|based\s+on)\s+(?:the\s+)?(?:provided\s+|uploaded\s+|given\s+)?"
    r"(?:handbook|document|file|book|textbook|slides?|chapter|content|source\s+material|provided\s+text|uploaded\s+notes?)\b"
    r")",
    re.IGNORECASE,
)


def _formula_relations(source_excerpt: str) -> list[str]:
    """Return full and chained equality forms that would reveal the rule."""
    compact = normalise_symbolic_evidence(source_excerpt).strip("|")
    if "=" not in compact:
        return []
    relations = [compact]
    parts = [part for part in compact.split("=") if part]
    if len(parts) > 2:
        relations.extend(f"{parts[0]}={part}" for part in parts[1:])
    return [relation for relation in relations if len(relation) >= 3]


def _formula_identifiers(value: str) -> set[str]:
    identifiers: set[str] = set()
    for token in re.findall(r"[A-Za-zΑ-Ωα-ω]+", value):
        if token.isupper() and 1 < len(token) <= 4:
            identifiers.update(character.casefold() for character in token)
        elif len(token) <= 4:
            identifiers.add(token.casefold())
    return identifiers


def validate_question_presentation(
    *,
    question_type: str,
    question_text: str,
    explanation: str | None,
    source_excerpt: str,
    requested_difficulty: str | None = None,
    declared_difficulty: str | None = None,
) -> None:
    """Reject student-facing wording that gives away answers or mentions files."""
    stem = str(question_text or "").strip()
    if not stem:
        raise ValueError("question_text must not be empty")
    if _DOCUMENT_REFERENCE.search(stem):
        raise ValueError(
            "question must be standalone and must not mention the source document"
        )
    if explanation and _DOCUMENT_REFERENCE.search(str(explanation)):
        raise ValueError(
            "explanation must teach the answer directly without mentioning the source document"
        )

    source_looks_like_code = bool(
        re.search(
            r"\b(def|return|select|from|where|class|function|const|let|var)\b",
            source_excerpt,
            re.IGNORECASE,
        )
    )
    source_relations = _formula_relations(source_excerpt)
    if (
        is_symbolic_evidence(source_excerpt)
        and source_relations
        and not source_looks_like_code
    ):
        compact_stem = normalise_symbolic_evidence(stem)
        source_identifiers = _formula_identifiers(source_excerpt)
        stem_identifiers = _formula_identifiers(stem) if "=" in stem else set()
        shared_identifiers = source_identifiers & stem_identifiers
        same_formula_structure = bool(
            len(source_identifiers) >= 2
            and len(shared_identifiers) >= 2
            and len(shared_identifiers) / len(source_identifiers) >= 0.75
        )
        if (
            any(relation in compact_stem for relation in source_relations)
            or same_formula_structure
        ):
            raise ValueError(
                "question stem reveals the answer-bearing source formula or equation"
            )

    if requested_difficulty and declared_difficulty:
        if declared_difficulty.casefold() != requested_difficulty.casefold():
            raise ValueError(
                f"question difficulty must be {requested_difficulty}"
            )


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
