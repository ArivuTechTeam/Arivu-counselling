from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.student import _ordered_approved_questions, list_quizzes
from app.lib.auth import CurrentProfile


class RecordingQuery:
    def __init__(self, service: "RecordingService", table: str) -> None:
        self.service = service
        self.table = table
        self.columns = ""
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []

    def select(self, columns: str):
        self.columns = columns
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values):
        self.in_filters.append((column, set(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = [dict(row) for row in self.service.tables.get(self.table, [])]
        for column, value in self.filters:
            if column == "questions.review_status":
                approved = {
                    q["id"]
                    for q in self.service.tables["questions"]
                    if q.get("review_status") == value
                }
                rows = [row for row in rows if row.get("question_id") in approved]
            else:
                rows = [row for row in rows if row.get(column) == value]
        for column, values in self.in_filters:
            rows = [row for row in rows if row.get(column) in values]
        self.service.calls.append((self.table, self.columns))
        return SimpleNamespace(data=rows)


class RecordingService:
    def __init__(self) -> None:
        set_ids = [f"set-{index}" for index in range(4)]
        variants = [
            {
                "id": f"variant-{set_index}-{variant_index}",
                "tenant_id": "tenant-1",
                "quiz_set_id": set_id,
                "variant_type": "mixed",
                "total_marks": 2,
                "time_limit_minutes": 10,
            }
            for set_index, set_id in enumerate(set_ids)
            for variant_index in range(3)
        ]
        questions = [
            {
                "id": f"question-{index}",
                "tenant_id": "tenant-1",
                "type": "mcq_single",
                "question_text": f"Question {index}",
                "options": [],
                "correct_answer": "A",
                "explanation": None,
                "marks": 1,
                "review_status": "approved",
                "embedding": [0.0] * 1536,
            }
            for index in range(len(variants) * 2)
        ]
        links = []
        for index, variant in enumerate(variants):
            for offset in range(2):
                links.append(
                    {
                        "tenant_id": "tenant-1",
                        "variant_id": variant["id"],
                        "question_id": questions[index * 2 + offset]["id"],
                        "order_index": offset,
                    }
                )
        self.tables = {
            "enrollments": [
                {"tenant_id": "tenant-1", "profile_id": "student-1", "course_id": "course-1"}
            ],
            "subjects": [
                {"id": "subject-1", "tenant_id": "tenant-1", "course_id": "course-1", "name": "Math"}
            ],
            "quiz_sets": [
                {
                    "id": set_id,
                    "tenant_id": "tenant-1",
                    "title": f"Quiz {index}",
                    "published_at": "2026-09-10T00:00:00Z",
                    "subject_id": "subject-1",
                    "chapter_id": None,
                    "status": "published",
                }
                for index, set_id in enumerate(set_ids)
            ],
            "quiz_variants": variants,
            "quiz_variant_questions": links,
            "questions": questions,
            "quiz_attempts": [],
        }
        self.calls: list[tuple[str, str]] = []

    def table(self, name: str) -> RecordingQuery:
        return RecordingQuery(self, name)


class StudentQuizQueryEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RecordingService()
        self.profile = CurrentProfile(
            user_id="student-1", tenant_id="tenant-1", role="student"
        )

    def test_dashboard_catalog_uses_constant_batched_query_count(self) -> None:
        with patch("app.api.student.get_service_client", return_value=self.service):
            quizzes = list_quizzes(self.profile)

        self.assertEqual(len(quizzes), 4)
        self.assertEqual(len(self.service.calls), 7)
        self.assertEqual(
            sum(1 for table, _ in self.service.calls if table == "quiz_variants"), 1
        )
        self.assertEqual(
            sum(
                1
                for table, _ in self.service.calls
                if table == "quiz_variant_questions"
            ),
            1,
        )
        self.assertFalse(any(columns == "*" for _, columns in self.service.calls))

    def test_attempt_question_load_does_not_select_embedding(self) -> None:
        questions = _ordered_approved_questions(
            self.service, "variant-0-0", "tenant-1"
        )

        self.assertEqual(len(questions), 2)
        question_selects = [
            columns for table, columns in self.service.calls if table == "questions"
        ]
        self.assertEqual(
            question_selects,
            [
                "id, type, question_text, options, correct_answer, explanation, marks"
            ],
        )


if __name__ == "__main__":
    unittest.main()
