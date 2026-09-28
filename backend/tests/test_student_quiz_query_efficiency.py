from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.practice import _load_questions
from app.api.student import StudentQuizOut, _ordered_approved_questions, list_quizzes
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

    def limit(self, value: int):
        self.row_limit = value
        return self

    def execute(self):
        rows = [dict(row) for row in self.service.tables.get(self.table, [])]
        if self.table == "quiz_variant_questions" and "questions!inner" in self.columns:
            questions = {
                question["id"]: question
                for question in self.service.tables.get("questions", [])
            }
            rows = [
                {
                    **row,
                    "questions": {
                        "id": row["question_id"],
                        "type": questions[row["question_id"]]["type"],
                    },
                }
                for row in rows
                if row.get("question_id") in questions
            ]
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
        return SimpleNamespace(data=rows[: getattr(self, "row_limit", len(rows))])


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
        variants[0]["time_limit_minutes"] = None
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
                        "marks_override": 3 if index == 0 and offset == 0 else None,
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
                    "created_at": f"2026-09-{10 - index:02d}T00:00:00Z",
                    "subject_id": "subject-1",
                    "chapter_id": None,
                    "status": "published",
                    "audience_mode": "legacy_course",
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

    def rpc(self, name: str, params: dict):
        self.calls.append((name, str(params)))
        variants_by_set: dict[str, list[dict]] = {}
        for variant in self.tables["quiz_variants"]:
            variants_by_set.setdefault(variant["quiz_set_id"], []).append({
                "id": variant["id"], "variant_type": variant["variant_type"],
                "total_marks": variant["total_marks"],
                "time_limit_minutes": variant.get("time_limit_minutes") or 2,
                "question_count": 2, "attempted": False, "attempt_count": 0,
                "attempt_limit": params["p_attempt_limit"],
                "attempts_remaining": params["p_attempt_limit"], "best_pct": None,
            })
        payload = [{
            "id": row["id"], "title": row["title"],
            "published_at": row["published_at"], "subject_id": row["subject_id"],
            "chapter_id": row["chapter_id"], "subject_name": "Math",
            "chapter_name": None, "variants": variants_by_set[row["id"]],
            "_cursor_at": row["created_at"],
        } for row in self.tables["quiz_sets"]]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=payload))


class StudentQuizQueryEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = RecordingService()
        self.profile = CurrentProfile(
            user_id="student-1", tenant_id="tenant-1", role="student"
        )

    def test_dashboard_catalog_uses_constant_batched_query_count(self) -> None:
        with (
            patch("app.api.student.get_service_client", return_value=self.service),
            patch(
                "app.api.student.get_settings",
                return_value=SimpleNamespace(student_quiz_attempt_limit=4),
            ),
        ):
            page = list_quizzes(self.profile)

        quizzes = page.items

        self.assertEqual(len(quizzes), 4)
        self.assertEqual(quizzes[0].variants[0].time_limit_minutes, 2)
        self.assertEqual(quizzes[0].variants[0].attempt_limit, 4)
        self.assertEqual(quizzes[0].variants[0].attempts_remaining, 4)
        StudentQuizOut.model_validate(quizzes[0])
        self.assertFalse(hasattr(quizzes[0].variants[0], "quiz_set_id"))
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(self.service.calls[0][0], "student_quiz_catalog_page")
        self.assertIn("'p_tenant': 'tenant-1'", self.service.calls[0][1])
        self.assertIn("'p_student': 'student-1'", self.service.calls[0][1])

    def test_attempt_question_load_does_not_select_embedding(self) -> None:
        questions = _ordered_approved_questions(
            self.service, "variant-0-0", "tenant-1"
        )

        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["marks"], 3)
        self.assertEqual(questions[1]["marks"], 1)
        question_selects = [
            columns for table, columns in self.service.calls if table == "questions"
        ]
        self.assertEqual(
            question_selects,
            [
                "id, type, question_text, options, correct_answer, explanation, marks, figure_id"
            ],
        )

    def test_practice_question_load_does_not_select_embedding(self) -> None:
        questions = _load_questions(
            self.service,
            ["question-0", "question-1"],
            "tenant-1",
        )

        self.assertEqual(len(questions), 2)
        question_selects = [
            columns for table, columns in self.service.calls if table == "questions"
        ]
        self.assertEqual(
            question_selects,
            [
                "id, chapter_id, type, question_text, options, correct_answer, explanation, marks, figure_id"
            ],
        )


if __name__ == "__main__":
    unittest.main()
