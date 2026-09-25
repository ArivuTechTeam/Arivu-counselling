"""AI grading for descriptive answers in the paper bank (PYQ/MTP/RTP).

A descriptive question has no exact answer, so it is graded by comparing the
student's answer to the model answer's key points (the `answer_summary` captured at
extraction). A student who covers >= 90% of the key points earns the full marks,
else zero - the threshold the TL chose.

Batched: one AI call grades every descriptive answer in an attempt. A provider
failure or incomplete response must not turn a potentially correct answer into
zero marks; the caller returns a retryable error instead.
"""

from __future__ import annotations

import json
import logging
from math import isfinite

from app.services.ai_call_logging import ai_call_context
from app.services.llm.structured import complete_json_with_fallback

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 90


class DescriptiveGradingUnavailable(RuntimeError):
    """The provider did not return a complete, trustworthy grading result."""

_SYSTEM = """You are a strict but fair exam grader for descriptive / subjective answers.
For each item you get KEY POINTS a correct answer must contain (the model summary) and
the STUDENT'S answer. Judge how much of the key points the student's answer correctly
and clearly covers, as a percentage 0-100. Do NOT reward padding, irrelevant text, or a
restatement of the question. Return JSON ONLY, one entry per id:
{"grades":[{"id":"<id>","coverage":<0-100>}]}"""


def _user_prompt(items: list[dict]) -> str:
    rows = [
        {
            "id": it["question_id"],
            "model_key_points": (it.get("answer_summary") or it.get("model_answer") or "")[:2000],
            "student_answer": str(it.get("student_answer") or "")[:2000],
        }
        for it in items
    ]
    return "Grade each answer against its key points:\n" + json.dumps(
        {"items": rows}, ensure_ascii=False
    )


def grade_descriptive(items: list[dict], *, tenant_id: str | None = None) -> dict[str, bool]:
    """Return {question_id: passed}. `items` need question_id, answer_summary (or
    model_answer) and student_answer. A blank student answer or a question with no
    key points is an automatic fail (never sent to the model)."""
    passed = {it["question_id"]: False for it in items}
    gradeable = [
        it for it in items
        if (it.get("answer_summary") or it.get("model_answer"))
        and str(it.get("student_answer") or "").strip()
    ]
    if not gradeable:
        return passed
    try:
        with ai_call_context("descriptive_grading", tenant_id=tenant_id):
            data, _provider = complete_json_with_fallback(
                _SYSTEM, _user_prompt(gradeable), preferred_provider="deepseek"
            )
        grades = data.get("grades") if isinstance(data, dict) else None
        if not isinstance(grades, list) or len(grades) != len(gradeable):
            raise ValueError("Incomplete descriptive grades")
        expected_ids = {it["question_id"] for it in gradeable}
        seen_ids: set[str] = set()
        for grade in grades:
            if not isinstance(grade, dict):
                raise ValueError("Invalid descriptive grade")
            qid = grade.get("id")
            try:
                coverage = float(grade.get("coverage"))
            except (TypeError, ValueError):
                raise ValueError("Invalid descriptive coverage") from None
            if qid not in expected_ids or qid in seen_ids or not isfinite(coverage) or not 0 <= coverage <= 100:
                raise ValueError("Unexpected descriptive grade")
            seen_ids.add(qid)
            passed[qid] = coverage >= PASS_THRESHOLD
        if seen_ids != expected_ids:
            raise ValueError("Missing descriptive grade")
    except Exception as exc:  # noqa: BLE001 - never mistake provider failure for a wrong answer
        logger.warning("Descriptive grading unavailable (%s)", type(exc).__name__)
        raise DescriptiveGradingUnavailable from exc
    return passed
