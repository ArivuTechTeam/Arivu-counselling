from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.question_grounding import (
    validate_question_batch,
    validate_question_grounding,
)


DOMAIN_EVIDENCE = [
    ("physics", "The measured acceleration due to gravity is 9.81 metres per second squared."),
    ("chemistry", "One mole contains exactly 6.02214076 times ten to the power twenty three entities."),
    ("biology", "Mitochondria generate most cellular ATP through oxidative phosphorylation."),
    ("mathematics", "For a right triangle, the square of the hypotenuse equals the sum of the other squares."),
    ("history", "The treaty was signed in Versailles on 28 June 1919."),
    ("geography", "The Nile flows northward and empties into the Mediterranean Sea."),
    ("accounting", "Revenue expenditure is charged to the profit and loss account in the current period."),
    ("economics", "Opportunity cost is the value of the next best alternative forgone."),
    ("computer science", "Binary search halves the remaining sorted search interval after each comparison."),
    ("literature", "The repeated storm imagery reflects the narrator's increasing emotional conflict."),
]


def _question(excerpt: str, *, page: int = 1, **overrides):
    values = {
        "type": "true_false",
        "question_text": f"Is this statement supported: {excerpt}",
        "options": [
            {"id": "true", "text": "True"},
            {"id": "false", "text": "False"},
        ],
        "correct_answer": "true",
        "explanation": f"The source directly states that {excerpt}",
        "source_excerpt": excerpt,
        "source_page_start": page,
        "source_page_end": page,
        "grounding_confidence": 0.95,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(("domain", "excerpt"), DOMAIN_EVIDENCE)
def test_exact_source_evidence_verifies_across_subjects(domain: str, excerpt: str) -> None:
    material = f"=== SOURCE PAGE 1 ===\n{domain.title()} notes. {excerpt}"
    result = validate_question_grounding(_question(excerpt), material)
    assert result.status == "verified"
    assert result.warnings == []


def test_missing_or_invented_evidence_is_blocked() -> None:
    material = "=== SOURCE PAGE 2 ===\nThe archive records a tax of twelve silver coins."
    result = validate_question_grounding(
        _question("The archive records a tax of ninety gold coins.", page=2), material
    )
    assert result.status == "unsupported"
    assert any("not found" in warning for warning in result.warnings)


def test_wrong_page_and_malformed_answer_are_blocked() -> None:
    excerpt = "The archive records a tax of twelve silver coins."
    material = f"=== SOURCE PAGE 2 ===\n{excerpt}"
    result = validate_question_grounding(
        _question(excerpt, page=9, correct_answer="not-an-option"), material
    )
    assert result.status == "unsupported"
    assert any("answer shape" in warning for warning in result.warnings)
    assert any("source pages" in warning for warning in result.warnings)


def test_empty_or_generic_explanation_is_blocked() -> None:
    excerpt = "Revenue expenditure is charged in the current accounting period."
    material = f"=== SOURCE PAGE 3 ===\n{excerpt}"
    result = validate_question_grounding(
        _question(excerpt, page=3, explanation="Because it is correct"), material
    )
    assert result.status == "unsupported"
    assert any("Explanation is too generic" in warning for warning in result.warnings)


def test_near_duplicate_questions_are_blocked() -> None:
    excerpt = "Binary search halves the remaining sorted interval after each comparison."
    material = f"=== SOURCE PAGE 4 ===\n{excerpt}"
    first = _question(excerpt, page=4, question_text="What does binary search halve after each comparison?")
    second = _question(excerpt, page=4, question_text="What does binary search halve after each comparison")
    checks = validate_question_batch([first, second], material)
    assert [check.status for check in checks] == ["unsupported", "unsupported"]
    assert all(any("duplicate" in warning.lower() for warning in check.warnings) for check in checks)


@pytest.mark.parametrize(
    "formula",
    ["V = IR", "F = ma", "PE = mgh", "H₂O", "x = 5", "E = mc²"],
)
def test_short_symbolic_evidence_is_valid(formula: str) -> None:
    material = f"=== SOURCE PAGE 2 ===\n- Formula: {formula}"
    result = validate_question_grounding(_question(formula, page=2), material)
    assert result.status == "verified"
    assert not any("too short" in warning for warning in result.warnings)


def test_unicode_superscript_matches_plain_extracted_notation() -> None:
    result = validate_question_grounding(
        _question("P = VI = I²R", page=2),
        "=== SOURCE PAGE 2 ===\n- Formula: P = VI = I2R",
    )
    assert result.status == "verified"


def test_formula_application_is_verified_as_a_derivation() -> None:
    question = _question(
        "V = IR",
        page=2,
        type="mcq_single",
        question_text="Calculate V when I is 3 A and R is 5 ohms.",
        options=[{"id": "a", "text": "15 V"}, {"id": "b", "text": "8 V"}],
        correct_answer="a",
        explanation="Substituting the supplied values into V = IR gives 15 volts.",
    )
    result = validate_question_grounding(
        question, "=== SOURCE PAGE 2 ===\n- Formula: V = IR"
    )
    assert result.status == "verified"
    assert any("derived from" in warning.lower() for warning in result.warnings)


def test_semantic_formula_duplicates_are_blocked_even_with_different_wording() -> None:
    first = _question(
        "V = IR",
        page=2,
        question_text="Ohm's law states that voltage equals current times resistance.",
    )
    second = _question(
        "V = IR",
        page=2,
        type="mcq_single",
        question_text="Which equation correctly represents Ohm's law?",
        options=[{"id": "a", "text": "V = IR"}, {"id": "b", "text": "V = I/R"}],
        correct_answer="a",
    )
    checks = validate_question_batch(
        [first, second], "=== SOURCE PAGE 2 ===\n- Formula: V = IR"
    )
    assert [check.status for check in checks] == ["unsupported", "unsupported"]
    assert all(any("Semantic duplicate" in warning for warning in check.warnings) for check in checks)


def test_formula_applications_with_different_targets_are_not_duplicates() -> None:
    questions = [
        _question(
            "V = IR",
            page=2,
            question_text="A resistor of 5 ohms carries 3 A. What is the voltage across it?",
        ),
        _question(
            "V = IR",
            page=2,
            question_text="A circuit has 12 V and 4 ohms. What current flows through it?",
        ),
        _question(
            "V = IR",
            page=2,
            question_text="A component has 20 V and 2 A. What is its resistance?",
        ),
    ]

    checks = validate_question_batch(
        questions, "=== SOURCE PAGE 2 ===\n- Formula: V = IR"
    )

    assert [check.status for check in checks] == ["verified", "verified", "verified"]


def test_same_formula_application_target_is_a_semantic_duplicate() -> None:
    questions = [
        _question(
            "F = ma",
            page=4,
            question_text="A 4 kg mass accelerates at 3 m/s2. What net force acts on it?",
        ),
        _question(
            "F = ma",
            page=4,
            question_text="A 5 kg mass accelerates at 2 m/s2. What is the net force?",
        ),
    ]
    checks = validate_question_batch(
        questions, "=== SOURCE PAGE 4 ===\n- Formula: F = ma"
    )
    assert [check.status for check in checks] == ["unsupported", "unsupported"]


def test_formula_recall_and_worked_application_are_not_duplicates() -> None:
    questions = [
        _question(
            "KE = 1/2mv²",
            page=4,
            question_text="Which equation gives the kinetic energy of a moving object?",
        ),
        _question(
            "KE = 1/2mv²",
            page=4,
            question_text="A 2 kg object moves at 4 m/s. What is its kinetic energy?",
        ),
    ]
    checks = validate_question_batch(
        questions, "=== SOURCE PAGE 4 ===\n- Formula: KE = 1/2mv²"
    )
    assert [check.status for check in checks] == ["verified", "verified"]
