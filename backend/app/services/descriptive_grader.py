"""AI grading for descriptive answers in the paper bank (PYQ/MTP/RTP).

A descriptive question has no exact answer, so it is graded by comparing the
student's answer to the model answer's key points (the `answer_summary` captured at
extraction). A student who covers >= 90% of the key points earns the full marks,
else zero - the threshold the TL chose.

Batched: one AI call grades every descriptive answer in an attempt. Best-effort:
if the grader is unavailable, descriptive answers are marked "not passed" (0) rather
than failing the whole scorecard, so the student still gets their objective score.
"""

from __future__ import annotations

import json
import logging

from app.services.ai_call_logging import ai_call_context
from app.services.llm.structured import complete_json_with_fallback

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 90

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
        for grade in (data.get("grades") or []) if isinstance(data, dict) else []:
            qid = grade.get("id")
            try:
                coverage = float(grade.get("coverage"))
            except (TypeError, ValueError):
                coverage = 0.0
            if qid in passed:
                passed[qid] = coverage >= PASS_THRESHOLD
    except Exception:  # noqa: BLE001 - grading is best-effort; never break the scorecard
        logger.warning("Descriptive grading unavailable; marking descriptive as pending.")
    return passed
