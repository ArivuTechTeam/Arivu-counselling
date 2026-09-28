"""Slice 1 — rejected-question purge core.

Proves the publish-time purge: an unanswered rejected question (and its variant
link) is permanently deleted; an answered rejected question is preserved so
student history is never corrupted; approved/pending questions are untouched;
and each deletion writes a `question.purged_rejected` audit event.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services import events as events_module
from app.services.rejected_purge import purge_rejected_for_quiz_set


class _Query:
    def __init__(self, service: "_Service", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.operation = "select"
        self.payload = None

    def select(self, *_a):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.in_filters.append((key, set(values)))
        return self

    def limit(self, _n):
        return self

    def _matches(self, row: dict) -> bool:
        return all(row.get(k) == v for k, v in self.filters) and all(
            row.get(k) in vs for k, vs in self.in_filters
        )

    def execute(self):
        rows = self.service.tables.setdefault(self.table, [])
        matches = [r for r in rows if self._matches(r)]
        if self.operation == "insert":
            incoming = self.payload if isinstance(self.payload, list) else [self.payload]
            for item in incoming:
                rows.append(dict(item))
            return SimpleNamespace(data=[dict(i) for i in incoming])
        if self.operation == "delete":
            self.service.tables[self.table] = [r for r in rows if not self._matches(r)]
            return SimpleNamespace(data=[dict(r) for r in matches])
        return SimpleNamespace(data=[dict(r) for r in matches])


class _Service:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables

    def table(self, name: str) -> _Query:
        return _Query(self, name)


TENANT = "t1"
TEACHER = "teacher-1"
QUIZ = "quiz-1"


def _world() -> dict[str, list[dict]]:
    return {
        "quiz_variants": [{"id": "v1", "quiz_set_id": QUIZ, "tenant_id": TENANT}],
        "quiz_variant_questions": [
            {"variant_id": "v1", "question_id": "q1", "tenant_id": TENANT},
            {"variant_id": "v1", "question_id": "q2", "tenant_id": TENANT},
            {"variant_id": "v1", "question_id": "q3", "tenant_id": TENANT},
        ],
        "questions": [
            {"id": "q1", "tenant_id": TENANT, "created_by": TEACHER, "review_status": "approved"},
            {"id": "q2", "tenant_id": TENANT, "created_by": TEACHER, "review_status": "rejected"},
            {"id": "q3", "tenant_id": TENANT, "created_by": TEACHER, "review_status": "rejected"},
        ],
        # q3 was answered by a student; q2 was not.
        "attempt_answers": [{"question_id": "q3"}],
        "practice_answers": [],
        "events": [],
    }


class RejectedPurgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tables = _world()
        self.service = _Service(self.tables)
        # events.log_events uses its own client — point it at the same fake.
        self._orig = events_module.get_service_client
        events_module.get_service_client = lambda: self.service

    def tearDown(self) -> None:
        events_module.get_service_client = self._orig

    def test_unanswered_rejected_is_purged_answered_is_kept(self) -> None:
        result = purge_rejected_for_quiz_set(self.service, TENANT, TEACHER, QUIZ)
        self.assertEqual(result, {"purged": 1, "kept": 1})

        ids = {q["id"] for q in self.tables["questions"]}
        self.assertNotIn("q2", ids, "unanswered rejected question should be deleted")
        self.assertIn("q3", ids, "answered rejected question must be preserved")
        self.assertIn("q1", ids, "approved question must be untouched")

        links = {l["question_id"] for l in self.tables["quiz_variant_questions"]}
        self.assertNotIn("q2", links, "purged question's variant link must be removed")
        self.assertIn("q3", links)
        self.assertIn("q1", links)

    def test_purge_writes_audit_event(self) -> None:
        purge_rejected_for_quiz_set(self.service, TENANT, TEACHER, QUIZ)
        purge_events = [
            e for e in self.tables["events"] if e["event_type"] == "question.purged_rejected"
        ]
        self.assertEqual(len(purge_events), 1)
        self.assertEqual(purge_events[0]["subject_id"], "q2")
        self.assertEqual(purge_events[0]["metadata"]["quiz_set_id"], QUIZ)

    def test_no_rejected_questions_is_a_noop(self) -> None:
        for q in self.tables["questions"]:
            q["review_status"] = "approved"
        result = purge_rejected_for_quiz_set(self.service, TENANT, TEACHER, QUIZ)
        self.assertEqual(result, {"purged": 0, "kept": 0})
        self.assertEqual(len(self.tables["questions"]), 3)
        self.assertEqual(self.tables["events"], [])

    def test_only_this_teachers_rejected_are_purged(self) -> None:
        self.tables["questions"][1]["created_by"] = "someone-else"
        result = purge_rejected_for_quiz_set(self.service, TENANT, TEACHER, QUIZ)
        # q2 belongs to another teacher -> not eligible; q3 answered -> kept.
        self.assertEqual(result, {"purged": 0, "kept": 1})
        self.assertIn("q2", {q["id"] for q in self.tables["questions"]})


if __name__ == "__main__":
    unittest.main()
