from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.academics import teacher_subject_metrics
from app.lib.auth import CurrentProfile


TENANT_ID = "00000000-0000-0000-0000-000000000001"
TEACHER_ID = "00000000-0000-0000-0000-000000000002"


class _Query:
    def __init__(self, service: "_Service", table: str) -> None:
        self.service = service
        self.table = table
        self.equals: list[tuple[str, object]] = []
        self.memberships: list[tuple[str, set[object]]] = []

    def select(self, *_args):
        return self

    def eq(self, column: str, value: object):
        self.equals.append((column, value))
        return self

    def in_(self, column: str, values: list[object]):
        self.memberships.append((column, set(values)))
        return self

    def execute(self):
        self.service.executed.append(self)
        rows = self.service.rows.get(self.table, [])
        for column, value in self.equals:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.memberships:
            rows = [row for row in rows if row.get(column) in values]
        return SimpleNamespace(data=rows)


class _Service:
    def __init__(self) -> None:
        self.executed: list[_Query] = []
        self.rpc_calls: list[tuple[str, dict]] = []
        self.rows = {
            "teacher_subjects": [
                {
                    "teacher_id": TEACHER_ID,
                    "tenant_id": TENANT_ID,
                    "subject_id": "s1",
                }
            ],
            "subjects": [
                {
                    "id": "s1",
                    "name": "Accounting",
                    "course_id": "c1",
                    "course_level_id": "l1",
                    "tenant_id": TENANT_ID,
                }
            ],
            "courses": [{"id": "c1", "name": "CA", "tenant_id": TENANT_ID}],
            "course_levels": [
                {"id": "l1", "name": "Foundation", "tenant_id": TENANT_ID}
            ],
            "chapters": [{"id": "ch1", "subject_id": "s1", "tenant_id": TENANT_ID}],
            "questions": [
                {
                    "chapter_id": "ch1",
                    "review_status": "pending_review",
                    "created_by": TEACHER_ID,
                    "tenant_id": TENANT_ID,
                },
                {
                    "chapter_id": "ch1",
                    "review_status": "approved",
                    "created_by": "other-teacher",
                    "tenant_id": TENANT_ID,
                },
                {
                    "id": "q-needs-edit",
                    "chapter_id": "ch1",
                    "review_status": "needs_edit",
                    "created_by": TEACHER_ID,
                    "tenant_id": TENANT_ID,
                },
            ],
            "quiz_sets": [
                {
                    "id": "qs1",
                    "subject_id": "s1",
                    "status": "published",
                    "created_by": TEACHER_ID,
                    "tenant_id": TENANT_ID,
                },
                {
                    "id": "qs2",
                    "subject_id": "s1",
                    "status": "published",
                    "created_by": "other-teacher",
                    "tenant_id": TENANT_ID,
                },
            ],
            "quiz_variants": [
                {"id": "v1", "quiz_set_id": "qs1", "total_marks": 10, "tenant_id": TENANT_ID},
                {"id": "v3", "quiz_set_id": "qs1", "total_marks": 20, "tenant_id": TENANT_ID},
                {"id": "v2", "quiz_set_id": "qs2", "total_marks": 20, "tenant_id": TENANT_ID},
            ],
            "quiz_attempts": [
                {"variant_id": "v1", "student_id": "student-1", "status": "graded", "total_score": 7, "tenant_id": TENANT_ID},
                {"variant_id": "v3", "student_id": "student-2", "status": "graded", "total_score": 20, "tenant_id": TENANT_ID},
                {"variant_id": "v1", "student_id": "student-2", "status": "in_progress", "total_score": None, "tenant_id": TENANT_ID},
                {"variant_id": "v2", "student_id": "student-3", "status": "graded", "total_score": 20, "tenant_id": TENANT_ID},
            ],
        }

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict):
        self.rpc_calls.append((name, params))
        metric = {
            "id": "s1",
            "name": "Accounting",
            "course_name": "CA",
            "level_name": "Foundation",
            "chapters": 1,
            "quizzes_total": 1,
            "quizzes_published": 1,
            "quizzes_draft": 0,
            "questions": 2,
            "pending_review": 1,
            "needs_edit": 1,
            "attempts": 2,
            "students": 2,
            "avg_score_pct": 90.0,
            "score_earned": 27.0,
            "score_possible": 30.0,
        }
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[metric]))


class TeacherSubjectMetricsTests(unittest.TestCase):
    def test_metrics_are_tenant_scoped_teacher_owned_and_graded(self) -> None:
        service = _Service()
        profile = CurrentProfile(
            user_id=TEACHER_ID,
            tenant_id=TENANT_ID,
            role="teacher",
        )

        with patch("app.api.academics.get_service_client", return_value=service):
            result = teacher_subject_metrics(profile)

        self.assertEqual(len(result), 1)
        metric = result[0]
        self.assertEqual(metric["quizzes_total"], 1)
        self.assertEqual(metric["course_name"], "CA")
        self.assertEqual(metric["level_name"], "Foundation")
        self.assertEqual(metric["questions"], 2)
        self.assertEqual(metric["pending_review"], 1)
        self.assertEqual(metric["needs_edit"], 1)
        self.assertEqual(metric["attempts"], 2)
        self.assertEqual(metric["students"], 2)
        self.assertEqual(metric["avg_score_pct"], 90.0)

        self.assertEqual(service.executed, [])
        self.assertEqual(
            service.rpc_calls,
            [
                (
                    "teacher_subject_metrics",
                    {"p_tenant": TENANT_ID, "p_teacher": TEACHER_ID},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
