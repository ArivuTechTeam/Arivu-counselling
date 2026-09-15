from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.documents import DuplicateCheckRequest, check_duplicate
from app.lib.auth import CurrentProfile


class _Query:
    """Minimal PostgREST-style query recorder for the duplicate check.

    Distinguishes the three shapes check_duplicate uses: the current-document
    fetch (`.maybe_single()`), the chapter get-or-create, and the "others with
    the same hash under this chapter" list query.
    """

    def __init__(self, table: str, service: "_Service") -> None:
        self.table = table
        self.service = service
        self.op = "select"
        self.payload: dict | None = None
        self.single = False
        self.filters: list[tuple[str, str, object]] = []

    def select(self, *_a):
        self.op = "select"
        return self

    def insert(self, payload: dict):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload: dict):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        return self.service.handle(self)


class _Service:
    def __init__(
        self, current_doc: dict, others: list[dict], chapter_id: str | None = "chapter-1"
    ) -> None:
        self.current_doc = current_doc
        self.others = others
        self.chapter_id = chapter_id
        self.updates: list[dict] = []
        self.document_filters: list[tuple[str, str, object]] = []

    def table(self, name: str) -> _Query:
        return _Query(name, self)

    def handle(self, q: _Query):
        if q.table == "chapters":
            return SimpleNamespace(
                data=[{"id": self.chapter_id}] if self.chapter_id else []
            )
        if q.table == "documents":
            if q.op == "update":
                self.updates.append(q.payload)
                return SimpleNamespace(data=[q.payload])
            if q.single:  # current-document fetch
                return SimpleNamespace(data=self.current_doc)
            self.document_filters = q.filters
            return SimpleNamespace(data=self.others)  # same-hash "others" query
        return SimpleNamespace(data=[])


def _teacher() -> CurrentProfile:
    return CurrentProfile(user_id="teacher-1", tenant_id="tenant-1", role="teacher")


def _req() -> DuplicateCheckRequest:
    return DuplicateCheckRequest(
        document_id="doc-2", subject_id="subject-1", chapter_name="Chapter 1"
    )


class DuplicateCheckTests(unittest.TestCase):
    def test_flags_same_file_under_same_subject_and_chapter(self) -> None:
        service = _Service(
            current_doc={
                "id": "doc-2",
                "storage_path": "tenant-1/doc-2.pdf",
                "content_hash": "HASH",
                "chapter_id": None,
            },
            others=[{"original_filename": "first.pdf", "created_at": "2026-09-11T09:00:00+00:00"}],
        )
        with patch("app.api.documents.get_service_client", return_value=service), patch(
            "app.api.documents.teacher_has_subject", return_value=True
        ):
            result = check_duplicate(_req(), _teacher())

        self.assertTrue(result.duplicate)
        self.assertEqual(result.previous_filename, "first.pdf")
        self.assertEqual(result.previous_uploaded_at, "2026-09-11")
        self.assertEqual(service.updates, [])
        self.assertIn(("neq", "status", "archived"), service.document_filters)

    def test_no_warning_when_file_is_new_here(self) -> None:
        service = _Service(
            current_doc={
                "id": "doc-2",
                "storage_path": "tenant-1/doc-2.pdf",
                "content_hash": "HASH",
                "chapter_id": None,
            },
            others=[],
        )
        with patch("app.api.documents.get_service_client", return_value=service), patch(
            "app.api.documents.teacher_has_subject", return_value=True
        ):
            result = check_duplicate(_req(), _teacher())

        self.assertFalse(result.duplicate)
        self.assertIsNone(result.previous_filename)

    def test_missing_chapter_does_not_create_records(self) -> None:
        service = _Service(
            current_doc={
                "id": "doc-2",
                "storage_path": "tenant-1/doc-2.pdf",
                "content_hash": "HASH",
                "chapter_id": None,
            },
            others=[],
            chapter_id=None,
        )
        with patch("app.api.documents.get_service_client", return_value=service), patch(
            "app.api.documents.teacher_has_subject", return_value=True
        ):
            result = check_duplicate(_req(), _teacher())

        self.assertFalse(result.duplicate)
        self.assertEqual(service.updates, [])

    def test_rejects_subject_the_teacher_does_not_own(self) -> None:
        service = _Service(current_doc={}, others=[])
        with patch("app.api.documents.get_service_client", return_value=service), patch(
            "app.api.documents.teacher_has_subject", return_value=False
        ):
            with self.assertRaises(Exception) as raised:
                check_duplicate(_req(), _teacher())
        self.assertEqual(getattr(raised.exception, "status_code", None), 404)


if __name__ == "__main__":
    unittest.main()
