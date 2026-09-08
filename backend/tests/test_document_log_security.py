from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.documents import document_file_url, document_log
from app.api.extraction import re_extract_quiz_endpoint
from app.lib.auth import CurrentProfile


def teacher_profile() -> CurrentProfile:
    return CurrentProfile(
        user_id="teacher-a",
        tenant_id="tenant-a",
        role="teacher",
    )


class RecordingQuery:
    def __init__(self, service: "RecordingService", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.single = False

    def select(self, *_args):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[str]):
        self.filters.append((column, tuple(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        self.service.calls.append((self.table, tuple(self.filters)))
        rows = self.service.rows.get(self.table, [])
        return SimpleNamespace(data=(rows[0] if rows else None) if self.single else rows)


class RecordingService:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[tuple[str, object], ...]]] = []

    def table(self, table: str) -> RecordingQuery:
        return RecordingQuery(self, table)

    def filters_for(self, table: str) -> list[tuple[tuple[str, object], ...]]:
        return [filters for called_table, filters in self.calls if called_table == table]


class DocumentLogSecurityTests(unittest.TestCase):
    def test_document_log_scopes_every_read_to_the_verified_tenant(self) -> None:
        service = RecordingService(
            {
                "documents": [
                    {
                        "id": "document-a",
                        "original_filename": "paper.pdf",
                        "file_type": "pdf",
                        "status": "completed",
                        "created_at": "2026-09-09T00:00:00+00:00",
                        "chapter_id": "chapter-a",
                    }
                ],
                "chapters": [
                    {"id": "chapter-a", "name": "Algebra", "subject_id": "subject-a"}
                ],
                "subjects": [{"id": "subject-a", "name": "Mathematics"}],
                "quiz_sets": [{"document_id": "document-a", "status": "draft"}],
                "ai_extraction_jobs": [],
            }
        )

        with patch("app.api.documents.get_service_client", return_value=service):
            result = document_log(teacher_profile())

        self.assertEqual(result[0].quiz_status, "draft")
        self.assertEqual(result[0].subject_name, "Mathematics")
        for table in ("documents", "chapters", "subjects", "quiz_sets", "ai_extraction_jobs"):
            self.assertTrue(service.filters_for(table), table)
            self.assertTrue(
                all(("tenant_id", "tenant-a") in filters for filters in service.filters_for(table)),
                table,
            )
        self.assertIn(
            ("uploaded_by", "teacher-a"),
            service.filters_for("documents")[0],
        )

    def test_signed_url_is_created_only_after_tenant_and_owner_lookup(self) -> None:
        service = RecordingService(
            {
                "documents": [
                    {
                        "storage_path": "tenant-a/document.pdf",
                        "original_filename": "paper.pdf",
                        "file_type": "pdf",
                    }
                ]
            }
        )

        with (
            patch("app.api.documents.get_service_client", return_value=service),
            patch(
                "app.api.documents.signed_url",
                return_value="https://storage.example/signed",
            ) as sign,
        ):
            result = document_file_url("document-a", teacher_profile())

        filters = service.filters_for("documents")[0]
        self.assertIn(("id", "document-a"), filters)
        self.assertIn(("tenant_id", "tenant-a"), filters)
        self.assertIn(("uploaded_by", "teacher-a"), filters)
        sign.assert_called_once_with("tenant-a/document.pdf", 300)
        self.assertEqual(result.url, "https://storage.example/signed")


class ReExtractionSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_scopes_document_and_chapter_before_running_ai(self) -> None:
        service = RecordingService(
            {
                "documents": [{"chapter_id": "chapter-a"}],
                "chapters": [{"subject_id": "subject-a"}],
            }
        )
        extracted = {"quiz_set_id": "quiz-a"}

        with (
            patch("app.api.extraction.get_service_client", return_value=service),
            patch("app.api.extraction.enforce_ai_rate_limit") as enforce,
            patch(
                "app.api.extraction.get_settings",
                return_value=SimpleNamespace(rate_limit_quiz_extraction_per_hour=10),
            ),
            patch(
                "app.api.extraction.run_in_threadpool",
                new=AsyncMock(return_value=extracted),
            ) as run,
        ):
            result = await re_extract_quiz_endpoint("document-a", teacher_profile())

        self.assertEqual(result, extracted)
        document_filters = service.filters_for("documents")[0]
        self.assertIn(("tenant_id", "tenant-a"), document_filters)
        self.assertIn(("uploaded_by", "teacher-a"), document_filters)
        self.assertIn(
            ("tenant_id", "tenant-a"),
            service.filters_for("chapters")[0],
        )
        enforce.assert_called_once()
        run.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
