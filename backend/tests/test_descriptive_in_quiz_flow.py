"""Descriptive questions must not reach, or cost marks in, the ordinary quiz flow.

They are extracted in paper mode and graded by AI in the paper-bank flow. In a
normal quiz they would get the wrong answer box, always score 0, and inflate the
denominator. Paper-bank grading itself is covered by tests/test_pyq.py.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.student import (
    StartAttemptRequest,
    SubmitRequest,
    SubmittedAnswer,
    _attempt_questions,
    get_attempt,
    start_attempt,
    submit_attempt,
)
from tests.test_student_experience import MutableService, profile

MCQ = {
    "id": "q1", "tenant_id": "t1", "review_status": "approved", "type": "mcq_single",
    "question_text": "Pick B", "options": [{"id": "A", "text": "A"}, {"id": "B", "text": "B"}],
    "correct_answer": "B", "explanation": None, "marks": 2,
}
TRUE_FALSE = {
    "id": "q2", "tenant_id": "t1", "review_status": "approved", "type": "true_false",
    "question_text": "True statement",
    "options": [{"id": "true", "text": "True"}, {"id": "false", "text": "False"}],
    "correct_answer": "true", "explanation": None, "marks": 1,
}
DESCRIPTIVE = {
    "id": "q3", "tenant_id": "t1", "review_status": "approved", "type": "descriptive",
    "question_text": "Explain the rule in detail", "options": None,
    "correct_answer": {"model_answer": "The rule is..."}, "explanation": None, "marks": 10,
}


def _service(questions: list[dict], *, attempts: list[dict] | None = None) -> MutableService:
    links = [
        {"tenant_id": "t1", "variant_id": "v1", "question_id": q["id"], "order_index": i}
        for i, q in enumerate(questions)
    ]
    return MutableService({
        "enrollments": [{"tenant_id": "t1", "profile_id": "u1", "course_id": "c1"}],
        "subjects": [{"id": "s1", "tenant_id": "t1", "course_id": "c1"}],
        "quiz_sets": [{"id": "set1", "tenant_id": "t1", "subject_id": "s1",
                       "status": "published", "title": "Mixed paper"}],
        "quiz_variants": [{"id": "v1", "tenant_id": "t1", "quiz_set_id": "set1",
                           "variant_type": "mixed", "total_marks": 3, "time_limit_minutes": 10}],
        "quiz_variant_questions": links,
        "questions": [dict(q) for q in questions],
        "quiz_attempts": attempts or [],
        "attempt_answers": [],
        "practice_sessions": [],
    })


def _patched(service):
    return (
        patch("app.api.student.get_service_client", return_value=service),
        patch("app.api.student.log_event"),
        patch("app.api.student.get_settings",
              return_value=SimpleNamespace(student_quiz_attempt_limit=3)),
    )


class DescriptiveInQuizFlowTests(unittest.TestCase):
    def _run(self, service, fn):
        a, b, c = _patched(service)
        with a, b, c:
            return fn()

    def test_new_attempt_does_not_present_descriptive_questions(self) -> None:
        service = _service([MCQ, TRUE_FALSE, DESCRIPTIVE])

        started = self._run(service, lambda: start_attempt(StartAttemptRequest(variant_id="v1"), profile()))

        self.assertEqual([q["id"] for q in started["questions"]], ["q1", "q2"])
        snapshot = service.tables["quiz_attempts"][0]["question_snapshot"]
        self.assertEqual([q["id"] for q in snapshot], ["q1", "q2"])

    def test_descriptive_marks_do_not_cost_the_student(self) -> None:
        service = _service([MCQ, TRUE_FALSE, DESCRIPTIVE])
        started = self._run(service, lambda: start_attempt(StartAttemptRequest(variant_id="v1"), profile()))

        # The student answers everything they were shown — nothing more is required.
        result = self._run(service, lambda: submit_attempt(
            started["attempt_id"],
            SubmitRequest(answers=[
                SubmittedAnswer(question_id="q1", student_answer="B"),
                SubmittedAnswer(question_id="q2", student_answer="true"),
            ]),
            profile(),
        ))

        self.assertEqual(result["total_score"], 3.0)
        self.assertEqual(result["max_score"], 3.0)  # was 13 with the descriptive 10
        self.assertEqual([r["id"] for r in result["results"]], ["q1", "q2"])
        self.assertTrue(all(r["is_correct"] for r in result["results"]))

    def test_objective_only_quiz_is_unchanged(self) -> None:
        service = _service([MCQ, TRUE_FALSE])
        started = self._run(service, lambda: start_attempt(StartAttemptRequest(variant_id="v1"), profile()))

        self.assertEqual(len(started["questions"]), 2)

    def test_quiz_with_only_descriptive_questions_cannot_be_started(self) -> None:
        service = _service([DESCRIPTIVE])

        with self.assertRaises(HTTPException) as caught:
            self._run(service, lambda: start_attempt(StartAttemptRequest(variant_id="v1"), profile()))

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(service.tables["quiz_attempts"], [])

    # Attempts frozen before this rule still carry the descriptive question.
    def _legacy_attempt(self, status: str, total_score: float) -> dict:
        return {
            "id": "legacy-1", "tenant_id": "t1", "variant_id": "v1", "student_id": "u1",
            "status": status, "total_score": total_score, "started_at": "2026-09-01T00:00:00+00:00",
            "question_snapshot": [MCQ, TRUE_FALSE, DESCRIPTIVE], "scoring_policy_snapshot": None,
        }

    def test_old_snapshot_is_filtered_when_read(self) -> None:
        questions = _attempt_questions(None, self._legacy_attempt("graded", 2.0), "t1")

        self.assertEqual([q["id"] for q in questions], ["q1", "q2"])

    def test_already_graded_attempt_shows_a_fair_denominator_and_keeps_its_score(self) -> None:
        legacy = self._legacy_attempt("graded", 2.0)
        service = _service([MCQ, TRUE_FALSE, DESCRIPTIVE], attempts=[legacy])
        service.tables["attempt_answers"] = [
            {"tenant_id": "t1", "attempt_id": "legacy-1", "question_id": "q1",
             "student_answer": "B", "is_correct": True, "marks_awarded": 2.0},
            {"tenant_id": "t1", "attempt_id": "legacy-1", "question_id": "q3",
             "student_answer": "typed into the wrong box", "is_correct": False, "marks_awarded": 0.0},
        ]

        result = self._run(service, lambda: get_attempt("legacy-1", profile()))

        self.assertEqual(result["total_score"], 2.0)   # stored score untouched
        self.assertEqual(result["max_score"], 3.0)     # was 13
        self.assertEqual([r["id"] for r in result["results"]], ["q1", "q2"])
        self.assertEqual(service.tables["quiz_attempts"][0]["total_score"], 2.0)

    def test_in_progress_old_attempt_no_longer_demands_a_descriptive_answer(self) -> None:
        legacy = self._legacy_attempt("in_progress", 0.0)
        service = _service([MCQ, TRUE_FALSE, DESCRIPTIVE], attempts=[legacy])

        taking = self._run(service, lambda: get_attempt("legacy-1", profile()))
        self.assertEqual([q["id"] for q in taking["questions"]], ["q1", "q2"])

        result = self._run(service, lambda: submit_attempt(
            "legacy-1",
            SubmitRequest(answers=[
                SubmittedAnswer(question_id="q1", student_answer="B"),
                SubmittedAnswer(question_id="q2", student_answer="true"),
            ]),
            profile(),
        ))
        self.assertEqual(result["max_score"], 3.0)


if __name__ == "__main__":
    unittest.main()
