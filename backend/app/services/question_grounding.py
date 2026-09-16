"""Subject-neutral deterministic grounding checks for generated questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.services.question_validation import validate_question_answer_shape
from app.services.source_material import (
    evidence_occurs_in_material,
    explicit_source_excerpts,
    is_meaningful_evidence,
    is_symbolic_evidence,
    material_page_ranges,
    normalise_evidence,
    normalise_symbolic_evidence,
    page_range_is_available,
)


_GENERIC_EXPLANATIONS = {
    "because it is correct",
    "this is the correct answer",
    "the answer is correct",
    "as stated above",
}

_APPLICATION_WORDS = re.compile(
    r"\b(calculate|compute|determine|find|solve|how much|what is the value)\b",
    re.IGNORECASE,
)

_TARGET_PATTERNS = (
    re.compile(
        r"\b(?:calculate|compute|determine|find|solve\s+for)\s+"
        r"(?:the\s+|a\s+|an\s+|its\s+|their\s+)?"
        r"([a-z][a-z -]{0,40}?)(?:\?|\bwhen\b|\bgiven\b|\busing\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+(?:is|are)?\s*(?:the\s+|a\s+|an\s+|its\s+|their\s+)?"
        r"([a-z][a-z -]{0,40}?)(?:\?|\bacross\b|\bthrough\b|\bacts\b|\busing\b)",
        re.IGNORECASE,
    ),
)

_TARGET_STOP_WORDS = {
    "a", "an", "the", "its", "their", "this", "that", "value", "result",
    "across", "through", "acting", "acts", "on", "it", "object", "component",
    "flow", "flows", "equals", "equal", "gives", "represents",
}


@dataclass
class GroundingCheck:
    status: str = "verified"
    warnings: list[str] = field(default_factory=list)

    def flag(self, status: str, message: str) -> None:
        priority = {"verified": 0, "needs_teacher_review": 1, "ambiguous": 2, "unsupported": 3}
        if priority[status] > priority[self.status]:
            self.status = status
        if message not in self.warnings:
            self.warnings.append(message)


def _meaningful_excerpt(excerpt: str) -> bool:
    return is_meaningful_evidence(excerpt)


def _question_target(text: str) -> str:
    for pattern in _TARGET_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        words = [
            word.casefold()
            for word in re.findall(r"[A-Za-z]+", match.group(1))
            if word.casefold() not in _TARGET_STOP_WORDS
        ]
        if words:
            return "-".join(words[:3])
    return "unknown"


def _looks_like_application(text: str, question_type: str) -> bool:
    if question_type == "numerical" or _APPLICATION_WORDS.search(text):
        return True
    # Subject-neutral word-problem signal: multiple stated numeric inputs and
    # a requested result. Years/dates may also satisfy this, but the target is
    # retained in the fingerprint so unrelated historical questions do not
    # collapse together.
    numeric_inputs = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", text)
    return len(numeric_inputs) >= 2 and bool(re.search(r"\bwhat\b|\bfind\b", text, re.I))


def _question_skill(question: Any) -> str:
    """Coarse intent used to catch semantic duplicates with different wording."""
    text = str(getattr(question, "question_text", "") or "")
    question_type = str(getattr(question, "type", ""))
    if _looks_like_application(text, question_type):
        return "application:" + _question_target(text)
    if re.search(r"\b(rearrang|solve\s+for|express\s+.+\s+in\s+terms)\b", text, re.I):
        return "rearrangement:" + _question_target(text)
    if question_type == "mcq_multi":
        return "selection"
    return "recall"


def validate_question_grounding(question: Any, material: str) -> GroundingCheck:
    """Validate one model question without making an AI call."""
    check = GroundingCheck()
    try:
        validate_question_answer_shape(
            str(question.type), question.options, question.correct_answer
        )
    except ValueError as exc:
        check.flag("unsupported", f"Invalid answer shape: {exc}")

    excerpt = str(getattr(question, "source_excerpt", "") or "").strip()
    if not _meaningful_excerpt(excerpt):
        check.flag("unsupported", "Source excerpt is missing or too short to verify.")
    elif not evidence_occurs_in_material(excerpt, material):
        check.flag("unsupported", "Source excerpt was not found in the selected material.")
    else:
        verified_excerpts = explicit_source_excerpts(material)
        if (
            verified_excerpts
            and not is_symbolic_evidence(excerpt)
            and not any(
                normalise_evidence(excerpt) in normalise_evidence(candidate)
                for candidate in verified_excerpts
            )
        ):
            check.flag(
                "unsupported",
                "Source excerpt does not match a verified original-document passage.",
            )

    page_start = getattr(question, "source_page_start", None)
    page_end = getattr(question, "source_page_end", None)
    if material_page_ranges(material):
        if not page_range_is_available(
            material, page_start, page_end, excerpt=excerpt
        ):
            check.flag("unsupported", "Claimed source pages are outside the selected material.")
    elif page_start is not None or page_end is not None:
        check.flag(
            "needs_teacher_review",
            "The source format has no stable page map; ignore the generated page reference.",
        )

    explanation = normalise_evidence(str(getattr(question, "explanation", "") or ""))
    if len(explanation) < 20 or explanation in _GENERIC_EXPLANATIONS:
        check.flag(
            "unsupported",
            "Explanation is too generic; confirm it teaches why the answer is correct.",
        )

    confidence = getattr(question, "grounding_confidence", None)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        check.flag("needs_teacher_review", "Grounding confidence is missing.")
    elif not 0 <= float(confidence) <= 1:
        check.flag("unsupported", "Grounding confidence must be between 0 and 1.")
    elif float(confidence) < 0.65:
        check.flag("needs_teacher_review", "The generator reported low grounding confidence.")

    if (
        check.status == "verified"
        and is_symbolic_evidence(excerpt)
        and _looks_like_application(
            str(getattr(question, "question_text", "") or ""),
            str(getattr(question, "type", "") or ""),
        )
    ):
        check.warnings.append(
            "Answer is derived from the verified formula or symbolic source evidence."
        )
    return check


def validate_question_batch(questions: list[Any], material: str) -> list[GroundingCheck]:
    """Run evidence/shape checks and flag near-duplicate question wording."""
    checks = [validate_question_grounding(question, material) for question in questions]
    normalised = [normalise_evidence(str(question.question_text)) for question in questions]
    fingerprints = []
    for question in questions:
        excerpt = str(getattr(question, "source_excerpt", "") or "")
        fingerprints.append(
            (
                normalise_symbolic_evidence(excerpt) if is_symbolic_evidence(excerpt) else "",
                _question_skill(question),
            )
        )
    for index, text in enumerate(normalised):
        for other_index in range(index):
            other = normalised[other_index]
            wording_duplicate = bool(
                text and other and SequenceMatcher(None, text, other).ratio() >= 0.9
            )
            semantic_duplicate = bool(
                fingerprints[index][0]
                and fingerprints[index] == fingerprints[other_index]
            )
            if wording_duplicate or semantic_duplicate:
                label = "Semantic duplicate" if semantic_duplicate else "Near-duplicate"
                checks[index].flag("unsupported", f"{label} of question {other_index + 1}.")
                checks[other_index].flag(
                    "unsupported", f"{label} of question {index + 1}."
                )
    return checks
