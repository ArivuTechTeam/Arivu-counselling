"""
Auto-grading engine — the most correctness-critical code in the product.

grade_answer(question, student_answer) -> (is_correct, marks_awarded)

One rule per question type. The rules rely on the EXACT correct_answer shapes
the generator/prompt produce (see quiz_prompts.py), which is why those shapes
had to be locked down. If a shape ever changes, this file changes with it.
"""

from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    """
    Loosely normalize free text for fill-in-the-blank grading so trivial
    differences don't mark a right answer wrong: lowercase, trim, collapse
    internal whitespace, and strip surrounding punctuation/quotes.
    """
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip(".,;:!?\"'()[]")


def grade_answer(question: dict, student_answer: Any) -> tuple[bool, float]:
    """Return (is_correct, marks_awarded) for one answered question."""
    marks = float(question.get("marks") or 1)
    is_correct = _is_correct(
        question["type"], question["correct_answer"], student_answer
    )
    return is_correct, (marks if is_correct else 0.0)


def _is_correct(q_type: str, correct: Any, student: Any) -> bool:
    # No answer submitted is always wrong (never a crash).
    if student is None:
        return False

    if q_type in ("mcq_single", "true_false"):
        # correct is an option id (or "true"/"false"); compare as strings.
        return str(student) == str(correct)

    if q_type == "mcq_multi":
        # All-or-nothing: the chosen SET must equal the correct SET exactly.
        return set(map(str, student or [])) == set(map(str, correct or []))

    if q_type == "numerical":
        # correct = {"value": <num>, "tolerance": <num>}; within tolerance = right.
        try:
            value = float(correct["value"])
            tolerance = float(correct.get("tolerance") or 0)
            return abs(float(student) - value) <= tolerance
        except (TypeError, ValueError, KeyError):
            return False

    if q_type == "fill_blank":
        # correct = {"answers": [...]}; normalized match against any accepted one.
        accepted = correct.get("answers") if isinstance(correct, dict) else None
        if not accepted:
            return False
        target = _normalize(str(student))
        return any(_normalize(str(a)) == target for a in accepted)

    # Unknown type: fail closed rather than silently award marks.
    return False
