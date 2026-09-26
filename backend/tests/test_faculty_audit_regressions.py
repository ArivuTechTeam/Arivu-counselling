from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.quiz import publish_quiz_set
from app.api.teacher import class_monitor, class_overview, student_report
from app.lib.auth import CurrentProfile
from app.lib.supabase_queries import select_all, select_all_in


TENANT = "tenant-a"
TEACHER = "teacher-a"


class _Query:
    def __init__(self, service: "_Service", table: str) -> None:
        self.service = service
        self.table = table
        self.equals: list[tuple[str, object]] = []
        self.memberships: list[tuple[str, set[object]]] = []
        self.single = False
        self.update_payload: dict | None = None
        self.deleting = False
        self.order_column: str | None = None
        self.order_desc = False
        self.bounds: tuple[int, int] | None = None

    def select(self, *_args):
        return self

    def eq(self, column: str, value: object):
        self.equals.append((column, value))
        return self

    def in_(self, column: str, values):
        self.memberships.append((column, set(values)))
        return self

    def order(self, column: str, *, desc: bool = False, **_kwargs):
        self.order_column = column
        self.order_desc = desc
        return self

    def range(self, start: int, end: int):
        self.bounds = (start, end)
        return self

    def limit(self, _count: int):
        return self

    def is_(self, column: str, _value: str):
        self.equals.append((column, None))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, payload: dict):
        self.update_payload = payload
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        self.service.calls.append(self)
        source = self.service.rows.setdefault(self.table, [])
        rows = [
            row
            for row in source
            if all(row.get(column) == value for column, value in self.equals)
            and all(row.get(column) in values for column, values in self.memberships)
        ]
        if self.deleting:
            removed = {id(row) for row in rows}
            self.service.rows[self.table] = [
                row for row in source if id(row) not in removed
            ]
            return SimpleNamespace(data=[dict(row) for row in rows])
        if self.update_payload is not None:
            for row in rows:
                row.update(self.update_payload)
        if self.order_column:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(self.order_column) or ""),
                reverse=self.order_desc,
            )
        if self.bounds:
            start, end = self.bounds
            rows = rows[start : end + 1]
        data = [dict(row) for row in rows]
        return SimpleNamespace(
            data=(data[0] if data else None) if self.single else data
        )


class _Service:
    def __init__(self, rows: dict[str, list[dict]] | None = None) -> None:
        self.rows = rows or {}
        self.calls: list[_Query] = []

    def table(self, name: str) -> _Query:
        return _Query(self, name)


def _teacher() -> CurrentProfile:
    return CurrentProfile(user_id=TEACHER, tenant_id=TENANT, role="teacher")


def _base_roster() -> dict[str, list[dict]]:
    return {
        "teacher_subjects": [
            {"id": "ts1", "tenant_id": TENANT, "teacher_id": TEACHER, "subject_id": "s1"}
        ],
        "subjects": [{"id": "s1", "tenant_id": TENANT, "course_id": "c1"}],
        "enrollments": [
            {"id": "e1", "tenant_id": TENANT, "course_id": "c1", "profile_id": "student-in"}
        ],
        "profiles": [
            {"id": "student-in", "tenant_id": TENANT, "role": "student", "full_name": "In Class"},
            {"id": "student-out", "tenant_id": TENANT, "role": "student", "full_name": "Outside Class"},
        ],
        "quiz_sets": [],
        "quiz_variants": [],
        "quiz_attempts": [],
    }


class PaginationTests(unittest.TestCase):
    def test_select_all_reads_every_page(self) -> None:
        service = _Service({"items": [{"id": str(i)} for i in range(5)]})
        with patch("app.lib.supabase_queries.POSTGREST_PAGE_SIZE", 2):
            rows = select_all(service, "items", "id")
        self.assertEqual([row["id"] for row in rows], ["0", "1", "2", "3", "4"])
        self.assertEqual(len(service.calls), 3)

    def test_select_all_in_batches_large_url_filters(self) -> None:
        service = _Service({"items": [{"id": str(i)} for i in range(5)]})
        with (
            patch("app.lib.supabase_queries.POSTGREST_FILTER_BATCH_SIZE", 2),
            patch("app.lib.supabase_queries.POSTGREST_PAGE_SIZE", 10),
        ):
            rows = select_all_in(
                service,
                "items",
                "id",
                in_column="id",
                values=["0", "1", "2", "3", "4"],
            )
        self.assertEqual([row["id"] for row in rows], ["0", "1", "2", "3", "4"])
        self.assertEqual(len(service.calls), 3)
        self.assertTrue(
            all(len(query.memberships[0][1]) <= 2 for query in service.calls)
        )


class FacultyRosterAuthorizationTests(unittest.TestCase):
    def test_class_monitor_uses_current_assignments_even_before_first_quiz(self) -> None:
        service = _Service(_base_roster())
        with patch("app.api.teacher.get_service_client", return_value=service):
            result = asyncio.run(class_monitor(_teacher()))
        self.assertEqual(result["summary"]["students"], 1)
        self.assertEqual(result["students"][0]["id"], "student-in")
        self.assertEqual(result["students"][0]["status"], "not_started")

    def test_student_report_rejects_same_tenant_student_outside_roster(self) -> None:
        service = _Service(_base_roster())
        with (
            patch("app.api.teacher.get_service_client", return_value=service),
            self.assertRaises(HTTPException) as raised,
        ):
            student_report("student-out", _teacher())
        self.assertEqual(raised.exception.status_code, 404)

    def test_student_report_allows_current_roster_student(self) -> None:
        service = _Service(_base_roster())
        with patch("app.api.teacher.get_service_client", return_value=service):
            result = student_report("student-in", _teacher())
        self.assertEqual(result["student"]["name"], "In Class")
        self.assertEqual(result["overall"]["quizzes_taken"], 0)

    def test_student_report_only_labels_topics_below_sixty_as_weak(self) -> None:
        rows = _base_roster()
        rows.update(
            {
                "quiz_sets": [
                    {"id": "set1", "tenant_id": TENANT, "created_by": TEACHER, "subject_id": "s1", "title": "Quiz"}
                ],
                "quiz_variants": [
                    {"id": "v1", "tenant_id": TENANT, "quiz_set_id": "set1", "total_marks": 2}
                ],
                "quiz_attempts": [
                    {"id": "a1", "tenant_id": TENANT, "variant_id": "v1", "student_id": "student-in", "status": "graded", "total_score": 1, "submitted_at": "2026-09-17T00:00:00Z"}
                ],
                "attempt_answers": [
                    {"id": "aa1", "tenant_id": TENANT, "attempt_id": "a1", "question_id": "q-weak", "is_correct": False},
                    {"id": "aa2", "tenant_id": TENANT, "attempt_id": "a1", "question_id": "q-strong", "is_correct": True},
                ],
                "questions": [
                    {"id": "q-weak", "tenant_id": TENANT, "topic_id": "t-weak"},
                    {"id": "q-strong", "tenant_id": TENANT, "topic_id": "t-strong"},
                ],
                "topics": [
                    {"id": "t-weak", "tenant_id": TENANT, "name": "Needs practice"},
                    {"id": "t-strong", "tenant_id": TENANT, "name": "Mastered"},
                ],
            }
        )
        service = _Service(rows)
        with patch("app.api.teacher.get_service_client", return_value=service):
            result = student_report("student-in", _teacher())
        self.assertEqual(result["weak_areas"], [{"topic": "Needs practice", "accuracy": 0, "answered": 1}])


class FacultyPublishingTests(unittest.TestCase):
    def _rows(self, statuses: list[tuple[str, str, float]]) -> dict[str, list[dict]]:
        return {
            "quiz_sets": [
                {
                    "id": "set1",
                    "tenant_id": TENANT,
                    "created_by": TEACHER,
                    "title": "Quiz",
                    "status": "draft",
                    "created_at": "2026-09-17T00:00:00Z",
                    "published_at": None,
                }
            ],
            "quiz_variants": [
                {"id": "v1", "tenant_id": TENANT, "quiz_set_id": "set1", "total_marks": 99}
            ],
            "quiz_variant_questions": [
                {
                    "id": f"link-{question_id}",
                    "tenant_id": TENANT,
                    "variant_id": "v1",
                    "question_id": question_id,
                }
                for question_id, _status, _marks in statuses
            ],
            "questions": [
                {
                    "id": question_id,
                    "tenant_id": TENANT,
                    "created_by": TEACHER,
                    "review_status": review_status,
                    "marks": marks,
                }
                for question_id, review_status, marks in statuses
            ],
        }

    def test_publish_blocks_pending_and_needs_edit_questions(self) -> None:
        for unresolved in ("pending_review", "needs_edit"):
            service = _Service(
                self._rows([("q1", "approved", 2), ("q2", unresolved, 3)])
            )
            with (
                self.subTest(unresolved=unresolved),
                patch("app.api.quiz.get_service_client", return_value=service),
                # Exercise the legacy (non-reuse) publish path this test verifies;
                # the reuse path enforces the same rules inside publish_quiz_atomic
                # (SQL), covered by scripts/test-quiz-reuse-db.mjs.
                patch("app.api.quiz.quiz_reuse.enabled", return_value=False),
                self.assertRaises(HTTPException) as raised,
            ):
                publish_quiz_set("set1", _teacher())
            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(service.rows["quiz_sets"][0]["status"], "draft")

    def test_publish_recalculates_marks_from_approved_questions(self) -> None:
        service = _Service(
            self._rows([("q1", "approved", 2), ("q2", "rejected", 5)])
        )
        with (
            patch("app.api.quiz.get_service_client", return_value=service),
            patch("app.api.quiz.log_event"),
            # Legacy (non-reuse) publish path: marks recalculation lives in Python
            # here; the reuse path recalculates inside publish_quiz_atomic (SQL).
            patch("app.api.quiz.quiz_reuse.enabled", return_value=False),
        ):
            result = publish_quiz_set("set1", _teacher())
        self.assertEqual(result["status"], "published")
        self.assertEqual(service.rows["quiz_variants"][0]["total_marks"], 2)

    def test_publish_purges_rejected_when_flag_on(self) -> None:
        service = _Service(self._rows([("q1", "approved", 2), ("q2", "rejected", 5)]))
        with (
            patch("app.api.quiz.get_service_client", return_value=service),
            patch("app.api.quiz.log_event"),
            patch("app.api.quiz.quiz_reuse.enabled", return_value=False),
            patch(
                "app.api.quiz.get_settings",
                return_value=SimpleNamespace(rejected_purge_enabled=True),
            ),
        ):
            result = publish_quiz_set("set1", _teacher())
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["purged_rejected"], 1)
        question_ids = {row["id"] for row in service.rows["questions"]}
        self.assertNotIn("q2", question_ids, "rejected question must be deleted on publish")
        self.assertIn("q1", question_ids, "approved question must remain")
        links = {row["question_id"] for row in service.rows["quiz_variant_questions"]}
        self.assertNotIn("q2", links, "the deleted question's variant link must be removed")

    def test_publish_keeps_rejected_when_flag_off(self) -> None:
        # Default flag (off): rejecting stays a soft-flag, byte-identical to
        # before — no deletion and no purged_rejected key in the response.
        service = _Service(self._rows([("q1", "approved", 2), ("q2", "rejected", 5)]))
        with (
            patch("app.api.quiz.get_service_client", return_value=service),
            patch("app.api.quiz.log_event"),
            patch("app.api.quiz.quiz_reuse.enabled", return_value=False),
            # Pin the flag OFF so the assertion is independent of the ambient .env.
            patch("app.api.quiz.get_settings",
                  return_value=SimpleNamespace(rejected_purge_enabled=False)),
        ):
            result = publish_quiz_set("set1", _teacher())
        self.assertEqual(result["status"], "published")
        self.assertNotIn("purged_rejected", result)
        question_ids = {row["id"] for row in service.rows["questions"]}
        self.assertIn("q2", question_ids, "rejected question must be preserved when flag is off")


class BlueprintPublishTests(unittest.TestCase):
    def _rows(self, statuses: list[tuple[str, str]]) -> dict[str, list[dict]]:
        return {
            "quiz_sets": [{
                "id": "set1", "tenant_id": TENANT, "created_by": TEACHER,
                "title": "Quiz", "status": "draft",
                "created_at": "2026-09-25T00:00:00Z", "published_at": None,
            }],
            "quiz_variants": [
                {"id": "v1", "tenant_id": TENANT, "quiz_set_id": "set1", "total_marks": 0}
            ],
            "quiz_variant_questions": [
                {"id": f"link-{qid}", "tenant_id": TENANT, "variant_id": "v1", "question_id": qid}
                for qid, _status in statuses
            ],
            "questions": [{
                "id": qid, "tenant_id": TENANT, "created_by": TEACHER,
                "type": "mcq_single", "question_text": f"Q {qid}",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answer": "a", "marks": 2, "review_status": status,
            } for qid, status in statuses]
        }

    def _publish(self, service, body):
        from app.api.quiz import BlueprintPublishRequest, blueprint_publish
        with (
            patch("app.api.quiz.get_service_client", return_value=service),
            patch("app.api.quiz.log_event"),
            patch("app.api.quiz.log_events"),
            patch("app.api.quiz.snapshot_published_pyq"),
            patch("app.api.questions._match_review_snapshot", side_effect=lambda query, row: query),
            patch("app.api.quiz.get_settings",
                  return_value=SimpleNamespace(extraction_blueprint_enabled=True)),
        ):
            return blueprint_publish("set1", BlueprintPublishRequest(**body), _teacher())

    def test_publishes_only_selected_and_leaves_rest_untouched(self) -> None:
        service = _Service(self._rows([("q1", "pending_review"), ("q2", "pending_review"), ("q3", "pending_review")]))
        result = self._publish(service, {"selected_question_ids": ["q1", "q2"]})
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["published_count"], 2)
        by_id = {q["id"]: q for q in service.rows["questions"]}
        self.assertEqual(by_id["q1"]["review_status"], "approved")
        self.assertEqual(by_id["q2"]["review_status"], "approved")
        # The unselected question is UNTOUCHED — still pending, still present.
        self.assertEqual(by_id["q3"]["review_status"], "pending_review")
        self.assertIn("q3", by_id)
        # Marks denominator reflects only the two published questions (2 marks each).
        self.assertEqual(service.rows["quiz_variants"][0]["total_marks"], 4)

    def test_empty_selection_is_rejected(self) -> None:
        service = _Service(self._rows([("q1", "pending_review")]))
        with self.assertRaises(HTTPException) as raised:
            self._publish(service, {"selected_question_ids": []})
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(service.rows["quiz_sets"][0]["status"], "draft")

    def test_flag_off_returns_404(self) -> None:
        service = _Service(self._rows([("q1", "pending_review")]))
        from app.api.quiz import BlueprintPublishRequest, blueprint_publish
        with (
            patch("app.api.quiz.get_service_client", return_value=service),
            patch("app.api.quiz.get_settings",
                  return_value=SimpleNamespace(extraction_blueprint_enabled=False)),
            self.assertRaises(HTTPException) as raised,
        ):
            blueprint_publish("set1", BlueprintPublishRequest(selected_question_ids=["q1"]), _teacher())
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(service.rows["quiz_sets"][0]["status"], "draft")


class FacultyDashboardMetricTests(unittest.TestCase):
    def test_at_risk_total_is_not_limited_to_preview_size(self) -> None:
        students = [f"student-{i}" for i in range(7)]
        service = _Service(
            {
                "quiz_sets": [
                    {"id": "set1", "tenant_id": TENANT, "created_by": TEACHER, "title": "Quiz", "status": "published"}
                ],
                "documents": [],
                "quiz_variants": [
                    {"id": "v1", "tenant_id": TENANT, "quiz_set_id": "set1", "total_marks": 10}
                ],
                "quiz_attempts": [
                    {
                        "id": f"a-{student}",
                        "tenant_id": TENANT,
                        "student_id": student,
                        "variant_id": "v1",
                        "status": "graded",
                        "total_score": 2,
                        "submitted_at": "2026-09-17T00:00:00Z",
                    }
                    for student in students
                ],
                "quiz_variant_questions": [],
                "profiles": [
                    {"id": student, "tenant_id": TENANT, "role": "student", "full_name": student}
                    for student in students
                ],
                "questions": [],
            }
        )
        with patch("app.api.teacher.get_service_client", return_value=service):
            result = asyncio.run(class_overview(_teacher()))
        self.assertEqual(result["at_risk"], 7)
        self.assertEqual(len(result["needs_attention"]), 6)
        self.assertIn("needs_edit", result["pipeline"])


if __name__ == "__main__":
    unittest.main()
