from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.admin import (
    admin_quiz_set_detail,
    admin_quiz_sets,
    admin_teacher_analytics,
    institution_analytics,
)
from app.api.institution_admin import router as institution_admin_router
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, service, table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.ordering: tuple[str, bool] | None = None

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[object]):
        self.in_filters.append((column, set(values)))
        return self

    def order(self, column: str, desc: bool = False):
        self.ordering = (column, desc)
        return self

    def execute(self):
        rows = [dict(row) for row in self.service.tables[self.table]]
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.in_filters:
            rows = [row for row in rows if row.get(column) in values]
        if self.ordering:
            column, desc = self.ordering
            rows.sort(key=lambda row: row.get(column) or "", reverse=desc)
        self.service.executed.append((self.table, list(self.filters)))
        return SimpleNamespace(data=rows)


class _Service:
    def __init__(self) -> None:
        self.executed: list[tuple[str, list[tuple[str, object]]]] = []
        self.tables = {
            "quiz_sets": [
                {"id": "set-a", "tenant_id": "tenant-a", "title": "Algebra", "status": "published", "subject_id": "subject-a", "created_by": "teacher-a", "created_at": "2026-09-08T10:00:00Z", "published_at": "2026-09-08T11:00:00Z"},
                {"id": "set-b", "tenant_id": "tenant-b", "title": "Hidden", "status": "published", "subject_id": "subject-b", "created_by": "teacher-b", "created_at": "2026-09-09T10:00:00Z", "published_at": None},
            ],
            "subjects": [
                {"id": "subject-a", "tenant_id": "tenant-a", "name": "Maths", "course_id": "course-a"},
                {"id": "subject-b", "tenant_id": "tenant-b", "name": "Secret", "course_id": "course-b"},
            ],
            "courses": [
                {"id": "course-a", "tenant_id": "tenant-a", "name": "B.Sc"},
                {"id": "course-b", "tenant_id": "tenant-b", "name": "Hidden course"},
            ],
            "profiles": [
                {"id": "teacher-a", "tenant_id": "tenant-a", "role": "teacher", "full_name": "Ada"},
                {"id": "teacher-inactive", "tenant_id": "tenant-a", "role": "teacher", "full_name": "No quizzes"},
                {"id": "student-a", "tenant_id": "tenant-a", "role": "student", "full_name": "Sam"},
                {"id": "teacher-b", "tenant_id": "tenant-b", "role": "teacher", "full_name": "Hidden"},
            ],
            "quiz_variants": [
                {"id": "variant-a1", "tenant_id": "tenant-a", "quiz_set_id": "set-a", "total_marks": 10},
                {"id": "variant-a2", "tenant_id": "tenant-a", "quiz_set_id": "set-a", "total_marks": 20},
                {"id": "variant-b", "tenant_id": "tenant-b", "quiz_set_id": "set-b", "total_marks": 10},
            ],
            "quiz_variant_questions": [
                {"tenant_id": "tenant-a", "variant_id": "variant-a1", "question_id": "question-a1"},
                {"tenant_id": "tenant-a", "variant_id": "variant-a1", "question_id": "question-a2"},
                {"tenant_id": "tenant-a", "variant_id": "variant-a2", "question_id": "question-a1"},
                {"tenant_id": "tenant-b", "variant_id": "variant-b", "question_id": "question-b"},
            ],
            "questions": [
                {"id": "question-a1", "tenant_id": "tenant-a", "question_text": "Solve x", "type": "mcq_single", "difficulty": "easy", "review_status": "pending_review"},
                {"id": "question-a2", "tenant_id": "tenant-a", "question_text": "Integrate y", "type": "numerical", "difficulty": "hard", "review_status": "approved"},
                {"id": "question-b", "tenant_id": "tenant-b", "question_text": "Hidden", "type": "true_false", "difficulty": "easy", "review_status": "approved"},
            ],
            "quiz_attempts": [
                {"id": "attempt-a1", "tenant_id": "tenant-a", "student_id": "student-a", "variant_id": "variant-a1", "status": "graded", "total_score": 8, "submitted_at": "2026-09-08T12:00:00Z"},
                {"id": "attempt-a2", "tenant_id": "tenant-a", "student_id": "student-a", "variant_id": "variant-a2", "status": "graded", "total_score": 5, "submitted_at": "2026-09-08T13:00:00Z"},
                {"id": "attempt-open", "tenant_id": "tenant-a", "student_id": "student-a", "variant_id": "variant-a1", "status": "in_progress", "total_score": 10, "submitted_at": None},
            ],
            "attempt_answers": [
                {"tenant_id": "tenant-a", "attempt_id": "attempt-a1", "question_id": "question-a1", "is_correct": True},
                {"tenant_id": "tenant-a", "attempt_id": "attempt-a1", "question_id": "question-a2", "is_correct": False},
                {"tenant_id": "tenant-a", "attempt_id": "attempt-a2", "question_id": "question-a1", "is_correct": False},
            ],
            "enrollments": [
                {"tenant_id": "tenant-a", "profile_id": "student-a", "course_id": "course-a"},
                {"tenant_id": "tenant-b", "profile_id": "student-b", "course_id": "course-b"},
            ],
        }

    def table(self, name: str) -> _Query:
        return _Query(self, name)


class AdminQuizPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.profile = CurrentProfile(user_id="admin-a", tenant_id="tenant-a", role="institution_admin")
        self.patch = patch("app.api.admin.get_service_client", return_value=self.service)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()

    def test_summary_aggregates_weighted_accuracy_reviews_and_attempts(self) -> None:
        rows = admin_quiz_sets(self.profile)

        self.assertEqual(len(rows), 1)
        quiz = rows[0]
        self.assertEqual(quiz.id, "set-a")
        self.assertEqual(quiz.teacher_id, "teacher-a")
        self.assertEqual(quiz.course_id, "course-a")
        self.assertEqual(quiz.questions, 2)
        self.assertEqual(quiz.attempts_count, 2)
        self.assertEqual(quiz.avg_accuracy, 43.3)
        self.assertEqual(quiz.review_status.pending, 1)
        self.assertEqual(quiz.review_status.approved, 1)
        self.assertEqual(quiz.last_attempted_at.isoformat(), "2026-09-08T13:00:00+00:00")

    def test_detail_returns_breakdowns_students_and_weak_questions(self) -> None:
        detail = admin_quiz_set_detail("set-a", self.profile)

        self.assertEqual(detail["question_breakdown"]["by_type"], {"mcq_single": 1, "numerical": 1})
        self.assertEqual(len(detail["student_performance"]), 2)
        self.assertEqual(detail["student_performance"][0]["student_name"], "Sam")
        self.assertEqual(detail["weak_questions"][0]["question_id"], "question-a2")
        self.assertEqual(detail["weak_questions"][0]["accuracy"], 0.0)

    def test_teacher_analytics_aggregates_activity_and_weighted_accuracy(self) -> None:
        result = admin_teacher_analytics(self.profile)

        self.assertEqual(result.summary.total_teachers, 2)
        self.assertEqual(result.summary.active_teachers, 1)
        self.assertEqual(result.summary.total_quiz_sets, 1)
        self.assertEqual(result.summary.total_published, 1)
        self.assertEqual(result.summary.total_attempts, 3)
        self.assertEqual(result.summary.avg_accuracy, 43.3)
        teacher = result.teachers[0]
        self.assertEqual(teacher.teacher_id, "teacher-a")
        self.assertEqual(teacher.quiz_sets_created, 1)
        self.assertEqual(teacher.quiz_sets_published, 1)
        self.assertEqual(teacher.total_attempts, 3)
        self.assertEqual(teacher.avg_accuracy, 43.3)
        self.assertEqual(teacher.course_names, ["B.Sc"])
        inactive = result.teachers[1]
        self.assertEqual(inactive.teacher_id, "teacher-inactive")
        self.assertFalse(inactive.is_active)
        self.assertEqual(inactive.quiz_sets_created, 0)
        self.assertEqual(inactive.total_attempts, 0)

    def test_quiz_set_teacher_filter_cannot_cross_tenants(self) -> None:
        own_rows = admin_quiz_sets(self.profile, teacher_id="teacher-a")
        other_rows = admin_quiz_sets(self.profile, teacher_id="teacher-b")

        self.assertEqual([row.id for row in own_rows], ["set-a"])
        self.assertEqual(other_rows, [])

    def test_every_teacher_analytics_query_is_tenant_scoped(self) -> None:
        admin_teacher_analytics(self.profile)

        for table, filters in self.service.executed:
            with self.subTest(table=table):
                self.assertIn(("tenant_id", "tenant-a"), filters)

    def test_every_performance_query_is_tenant_scoped(self) -> None:
        admin_quiz_set_detail("set-a", self.profile)

        for table, filters in self.service.executed:
            with self.subTest(table=table):
                self.assertIn(("tenant_id", "tenant-a"), filters)

    def test_institution_analytics_adds_actionable_drilldown_metrics(self) -> None:
        self.service.tables["profiles"].append(
            {"id": "student-risk", "tenant_id": "tenant-a", "role": "student", "full_name": "Riya"}
        )
        self.service.tables["quiz_attempts"].append(
            {"id": "attempt-risk", "tenant_id": "tenant-a", "student_id": "student-risk", "variant_id": "variant-a1", "status": "graded", "total_score": 1, "submitted_at": "2026-09-08T14:00:00Z"}
        )
        result = institution_analytics(self.profile)

        self.assertEqual(result.course_perf[0].course_id, "course-a")
        self.assertEqual(result.course_perf[0].pending_review, 1)
        self.assertEqual(result.teacher_activity[0].teacher_id, "teacher-a")
        self.assertTrue(result.teacher_activity[0].is_active)
        self.assertEqual(
            result.teacher_activity[0].last_quiz_created.isoformat(),
            "2026-09-08T10:00:00+00:00",
        )
        inactive = next(row for row in result.teacher_activity if row.teacher_id == "teacher-inactive")
        self.assertFalse(inactive.is_active)
        self.assertEqual(result.at_risk_students[0].student_id, "student-risk")
        self.assertEqual(result.at_risk_students[0].worst_quiz.title, "Algebra")
        self.assertEqual(result.at_risk_students[0].worst_quiz.accuracy, 10)

        for table, filters in self.service.executed:
            with self.subTest(table=table):
                self.assertIn(("tenant_id", "tenant-a"), filters)

    def test_summary_and_detail_routes_are_registered(self) -> None:
        registered = {
            (route.path, method)
            for route in institution_admin_router.routes
            for method in getattr(route, "methods", set())
        }

        self.assertIn(("/api/v1/admin/quiz-sets", "GET"), registered)
        self.assertIn(("/api/v1/admin/teachers/analytics", "GET"), registered)
        self.assertIn(
            ("/api/v1/admin/quiz-sets/{quiz_set_id}", "GET"),
            registered,
        )


if __name__ == "__main__":
    unittest.main()
