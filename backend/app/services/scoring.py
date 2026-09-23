"""Policy-driven per-question scoring (Phase 6.2).

`score(question, student_answer, policy)` returns an Outcome. The DEFAULT policy
reproduces today's behavior exactly, because for the default the engine delegates
correctness to the existing, proven `grade_answer` and simply awards full marks or
zero. Richer policies add:
  * negative marking      (wrong_penalty, penalty_is_fraction)
  * a blank vs wrong split (omission_score for a blank answer)
  * partial credit        (multi_mode = "mrm_partial", ACCA-style)
  * a numeric contract     (hook; the full unit/rounding logic lands in P6.2-4)

This is the most correctness-critical module in the program, so the default path
changes nothing: default policy + `grade_answer` == the current grader.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
)
from math import isfinite

from app.services.grading import grade_answer

_ROUNDING = {"nearest": ROUND_HALF_UP, "floor": ROUND_FLOOR, "ceil": ROUND_CEILING}

# State names for one graded answer.
CORRECT = "correct"
WRONG = "wrong"
BLANK = "blank"
PARTIAL = "partial"
NEEDS_MANUAL = "needs_manual"  # descriptive/essay — never silently scored 0

DEFAULT_POLICY: dict = {
    "wrong_penalty": 0.0,          # marks lost per wrong answer (>= 0)
    "penalty_is_fraction": False,  # true -> penalty = wrong_penalty * question marks
    "omission_score": 0.0,         # marks for a blank answer (usually 0)
    "multi_mode": "all_or_nothing",  # or "mrm_partial"
    "clamp_negative_total": True,  # floor the attempt total at 0
    "numeric": None,               # optional numeric contract (P6.2-4)
}


@dataclass
class Outcome:
    state: str
    awarded: float


def normalize_policy(raw: dict | None) -> dict:
    """Fill a (possibly partial or None) policy with defaults. None -> full/zero."""
    policy = dict(DEFAULT_POLICY)
    if isinstance(raw, dict):
        for key in DEFAULT_POLICY:
            if key in raw and raw[key] is not None:
                policy[key] = raw[key]
    for key in ("wrong_penalty", "omission_score"):
        try:
            value = float(policy[key])
        except (TypeError, ValueError):
            value = float(DEFAULT_POLICY[key])
        policy[key] = value if isfinite(value) else float(DEFAULT_POLICY[key])
    policy["wrong_penalty"] = max(0.0, policy["wrong_penalty"])
    for key in ("penalty_is_fraction", "clamp_negative_total"):
        if not isinstance(policy[key], bool):
            policy[key] = DEFAULT_POLICY[key]
    if policy["multi_mode"] not in {"all_or_nothing", "mrm_partial"}:
        policy["multi_mode"] = DEFAULT_POLICY["multi_mode"]
    if policy["numeric"] is not None and not isinstance(policy["numeric"], dict):
        policy["numeric"] = None
    return policy


def _is_answered(value) -> bool:
    """Matches the student-side notion of 'answered' (see practice.is_answered)."""
    if value is None or value == "":
        return False
    if isinstance(value, list):
        return len(value) > 0
    return True


def _score_mrm(question: dict, student_answer, marks: float) -> Outcome:
    """ACCA-style multiple-response-multiple-marks: award per correct selection,
    minus wrong selections, floored at 0."""
    correct = set(map(str, question.get("correct_answer") or []))
    chosen = set(map(str, student_answer or []))
    n = len(correct)
    if n == 0:
        return Outcome(WRONG, 0.0)
    net_correct = max(0, len(chosen & correct) - len(chosen - correct))
    awarded = marks * net_correct / n
    if awarded >= marks:
        return Outcome(CORRECT, marks)
    if awarded <= 0:
        return Outcome(WRONG, 0.0)
    return Outcome(PARTIAL, awarded)


def _numeric_correct(question: dict, student_answer, contract: dict) -> bool:
    """Contract-aware numerical comparison using Decimal (commerce numerics).

    Parses expected + student as Decimal, optionally rounds both to a declared
    number of decimals with a declared rounding mode, then compares within
    tolerance. Non-finite or unparseable values are wrong (never a crash). With
    no contract this path is not used — `grade_answer`'s float tolerance applies.
    """
    correct = question.get("correct_answer") or {}
    try:
        expected = Decimal(str(correct.get("value")))
        student = Decimal(str(student_answer))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not (expected.is_finite() and student.is_finite()):
        return False
    try:
        tolerance = max(
            Decimal(0),
            Decimal(str(contract.get("tolerance", correct.get("tolerance", 0)) or 0)),
        )
    except (InvalidOperation, TypeError, ValueError):
        tolerance = Decimal(0)
    decimals = contract.get("decimals")
    if decimals is not None:
        try:
            decimal_places = min(10, max(0, int(decimals)))
            quantum = Decimal(1).scaleb(-decimal_places)
            rounding = _ROUNDING.get(contract.get("rounding", "nearest"), ROUND_HALF_UP)
            expected = expected.quantize(quantum, rounding=rounding)
            student = student.quantize(quantum, rounding=rounding)
        except (InvalidOperation, TypeError, ValueError):
            return False
    return abs(student - expected) <= tolerance


def score(question: dict, student_answer, policy: dict | None = None) -> Outcome:
    """Grade one answer under `policy` (None/default -> current full/zero)."""
    policy = normalize_policy(policy)
    q_type = question.get("type")
    marks = float(question.get("marks") or 1)

    if q_type == "descriptive":
        return Outcome(NEEDS_MANUAL, 0.0)
    if not _is_answered(student_answer):
        return Outcome(BLANK, float(policy["omission_score"] or 0.0))

    if q_type == "mcq_multi" and policy["multi_mode"] == "mrm_partial":
        return _score_mrm(question, student_answer, marks)

    # Numerical: use the numeric contract when the policy declares one, otherwise
    # the existing float-tolerance comparison inside grade_answer (unchanged).
    if q_type == "numerical" and policy["numeric"]:
        is_correct = _numeric_correct(question, student_answer, policy["numeric"])
    else:
        is_correct, _ = grade_answer(question, student_answer)
    if is_correct:
        return Outcome(CORRECT, marks)

    penalty = float(policy["wrong_penalty"] or 0.0)
    if policy["penalty_is_fraction"]:
        penalty *= marks
    return Outcome(WRONG, -penalty)


def total_from_outcomes(outcomes: list[Outcome], policy: dict | None = None) -> float:
    """Sum awarded marks; floor at 0 when the policy clamps (exam behaviour)."""
    policy = normalize_policy(policy)
    total = sum(o.awarded for o in outcomes)
    if policy["clamp_negative_total"]:
        total = max(0.0, total)
    return total
