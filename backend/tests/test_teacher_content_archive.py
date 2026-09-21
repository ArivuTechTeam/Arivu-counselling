from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.documents import archive_document, list_documents
from app.api.quiz import archive_quiz_set, list_quiz_sets, restore_quiz_set
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, db: dict[str, list[dict]], table: str) -> None:
        self.db = db
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.payload: dict | None = None
        self.single = False
        self.range_bounds: tuple[int, int] | None = None

    def select(self, *_args):
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def eq(self, key: str, value: object):
        self.filters.append((key, value))
        return self

    def neq(self, key: str, value: object):
        self.filters.append((f"!{key}", value))
        return self

    def range(self, start: int, end: int):
        self.range_bounds = (start, end)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        matches = [
            row
            for row in rows
            if all(
                row.get(k[1:]) != v if k.startswith("!") else row.get(k) == v
                for k, v in self.filters
            )
        ]
        if self.range_bounds:
            start, end = self.range_bounds
            matches = matches[start : end + 1]
        if self.payload is not None:
            for row in matches:
                row.update(self.payload)
            return SimpleNamespace(data=[dict(row) for row in matches])
        return SimpleNamespace(
            data=(dict(matches[0]) if matches else None) if self.single else [dict(r) for r in matches]
        )


class _Service:
    def __init__(self, db: dict[str, list[dict]]) -> None:
        self.db = db

    def table(self, name: str) -> _Query:
        return _Query(self.db, name)


def _teacher(tenant: str = "t1") -> CurrentProfile:
    return CurrentProfile(user_id="teacher-1", tenant_id=tenant, role="teacher")


class TeacherContentArchiveTests(unittest.TestCase):
    def test_archived_list_and_restore_preserve_content_and_isolate_owners(self):
        original = dict(id="archived", tenant_id="t1", created_by="teacher-1",
                        title="Commerce", status="archived", published_at=None)
        service = _Service({
            "quiz_sets": [original.copy(), dict(original, id="active", status="published"),
                          dict(original, id="foreign", tenant_id="other"),
                          dict(original, id="colleague", created_by="teacher-2")],
            "questions": [{"id": "q1", "review_status": "approved"}],
            "quiz_attempts": [{"id": "a1", "score": 8}],
        })
        with patch("app.api.quiz.get_service_client", return_value=service):
            self.assertEqual([r["id"] for r in list_quiz_sets(_teacher(), archived=True)], ["archived"])
            for inaccessible in ("foreign", "colleague"):
                with self.assertRaises(HTTPException) as raised:
                    restore_quiz_set(inaccessible, _teacher())
                self.assertEqual(raised.exception.status_code, 404)
            with self.assertRaises(HTTPException) as raised:
                restore_quiz_set("active", _teacher())
            self.assertEqual(raised.exception.status_code, 409)
            result = restore_quiz_set("archived", _teacher())
            self.assertEqual(result["status"], "draft")
            self.assertIsNone(result["published_at"])
            self.assertEqual(list_quiz_sets(_teacher(), archived=True), [])
            self.assertEqual({r["id"] for r in list_quiz_sets(_teacher())}, {"archived", "active"})
        self.assertEqual(service.db["questions"], [{"id": "q1", "review_status": "approved"}])
        self.assertEqual(service.db["quiz_attempts"], [{"id": "a1", "score": 8}])
        self.assertEqual(service.db["quiz_sets"][1]["status"], "published")

    def test_quiz_list_returns_only_the_requested_page(self) -> None:
        service = _Service({"quiz_sets": [
            {
                "id": "set1", "tenant_id": "t1", "created_by": "teacher-1",
                "title": "First", "status": "draft", "created_at": "2026-09-12T00:00:00Z",
                "published_at": None,
            },
            {
                "id": "set2", "tenant_id": "t1", "created_by": "teacher-1",
                "title": "Second", "status": "draft", "created_at": "2026-09-11T00:00:00Z",
                "published_at": None,
            },
        ]})
        with patch("app.api.quiz.get_service_client", return_value=service):
            first = list_quiz_sets(_teacher(), page=1, page_size=1)
            second = list_quiz_sets(_teacher(), page=2, page_size=1)

        self.assertEqual([row["id"] for row in first], ["set1"])
        self.assertEqual([row["id"] for row in second], ["set2"])

    def test_document_archive_is_owner_scoped_and_hidden_from_list(self) -> None:
        service = _Service({"documents": [{
            "id": "d1", "tenant_id": "t1", "uploaded_by": "teacher-1",
            "original_filename": "notes.pdf", "file_type": "pdf",
            "status": "completed", "created_at": "2026-09-12T00:00:00Z",
        }]})
        with patch("app.api.documents.get_service_client", return_value=service):
            result = archive_document("d1", _teacher())
            visible = list_documents(_teacher())

        self.assertEqual(result["status"], "archived")
        self.assertEqual(visible, [])
        self.assertEqual(service.db["documents"][0]["status"], "archived")

    def test_document_archive_rejects_another_tenant(self) -> None:
        service = _Service({"documents": [{
            "id": "d1", "tenant_id": "t1", "uploaded_by": "teacher-1",
            "status": "completed",
        }]})
        with patch("app.api.documents.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as raised:
                archive_document("d1", _teacher("other"))
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(service.db["documents"][0]["status"], "completed")

    def test_published_quiz_archive_unpublishes_without_deleting_attempts(self) -> None:
        service = _Service({
            "quiz_sets": [{
                "id": "set1", "tenant_id": "t1", "created_by": "teacher-1",
                "title": "Quiz", "status": "published",
                "created_at": "2026-09-12T00:00:00Z",
                "published_at": "2026-09-12T01:00:00Z",
            }],
            "quiz_attempts": [{"id": "attempt1", "tenant_id": "t1"}],
        })
        with patch("app.api.quiz.get_service_client", return_value=service):
            result = archive_quiz_set("set1", _teacher())
            visible = list_quiz_sets(_teacher())

        self.assertEqual(result["status"], "archived")
        self.assertIsNone(result["published_at"])
        self.assertEqual(visible, [])
        self.assertEqual(service.db["quiz_attempts"], [{"id": "attempt1", "tenant_id": "t1"}])


if __name__ == "__main__":
    unittest.main()
