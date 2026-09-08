from __future__ import annotations

import io
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from app.api.extraction import (
    _has_expected_signature,
    _require_teacher,
    extract_quiz_endpoint,
)
from app.lib.auth import CurrentProfile
from app.services.quiz_extraction import _extract_document_content, extract_quiz


def profile(role: str = "teacher") -> CurrentProfile:
    return CurrentProfile(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        role=role,
    )


def minimal_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


class _DocumentQuery:
    def __init__(self) -> None:
        self.operation = "select"

    def select(self, *_args):
        self.operation = "select"
        return self

    def insert(self, *_args):
        self.operation = "insert"
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        if self.operation == "insert":
            return SimpleNamespace(data=[{"id": "document-1"}])
        return SimpleNamespace(data=[])


class _DocumentService:
    def table(self, name: str) -> _DocumentQuery:
        if name != "documents":
            raise AssertionError(f"Unexpected table: {name}")
        return _DocumentQuery()


class _NoSubjectQuery:
    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=None)


class _NoSubjectService:
    def table(self, name: str) -> _NoSubjectQuery:
        if name != "teacher_subjects":
            raise AssertionError(f"Unexpected table: {name}")
        return _NoSubjectQuery()


class ExtractionValidationTests(unittest.TestCase):
    def test_extraction_is_teacher_only(self) -> None:
        _require_teacher(profile())
        for role in ("student", "institution_admin", "super_admin"):
            with self.subTest(role=role), self.assertRaises(HTTPException) as caught:
                _require_teacher(profile(role))
            self.assertEqual(caught.exception.status_code, 403)

    def test_supported_file_signatures_are_checked(self) -> None:
        self.assertTrue(_has_expected_signature("pdf", b"%PDF-1.7\n"))
        self.assertTrue(_has_expected_signature("png", b"\x89PNG\r\n\x1a\nrest"))
        self.assertTrue(_has_expected_signature("jpg", b"\xff\xd8\xffrest"))
        self.assertTrue(_has_expected_signature("docx", minimal_docx()))
        self.assertFalse(_has_expected_signature("pdf", b"not a pdf"))
        self.assertFalse(_has_expected_signature("docx", b"not a zip"))

    def test_unassigned_subject_stops_before_document_or_ai_access(self) -> None:
        with patch(
            "app.services.quiz_extraction.get_service_client",
            return_value=_NoSubjectService(),
        ):
            with self.assertRaisesRegex(ValueError, "Subject not found"):
                extract_quiz(
                    document_id="document-1",
                    subject_id="subject-1",
                    chapter_id="chapter-1",
                    profile=profile(),
                )


class ExtractionProviderTests(unittest.TestCase):
    def test_docx_uses_shared_provider_fallback(self) -> None:
        expected = ({"questions": []}, "deepseek")
        with (
            patch(
                "app.services.quiz_extraction.extract_text",
                return_value="Question text",
            ),
            patch(
                "app.services.quiz_extraction.complete_json_with_fallback",
                return_value=expected,
            ) as fallback,
            patch(
                "app.services.quiz_extraction.get_settings",
                return_value=SimpleNamespace(
                    extraction_text_chunk_chars=18000,
                    extraction_chunk_concurrency=4,
                ),
            ),
        ):
            result = _extract_document_content(content=b"docx", ext="docx")

        self.assertEqual(result, expected)
        fallback.assert_called_once()

    def test_typed_pdf_uses_text_fallback_not_vision(self) -> None:
        # A PDF with a real text layer must take the cheap text path and NEVER
        # touch vision — that's the whole point of smart routing.
        expected = ({"questions": []}, "gemini")
        with (
            patch(
                "app.services.quiz_extraction.extract_text",
                return_value="Q1. What is 2+2?  a) 3  b) 4  Answer: b" * 10,
            ),
            patch(
                "app.services.quiz_extraction.complete_json_with_fallback",
                return_value=expected,
            ) as fallback,
            patch(
                "app.services.quiz_extraction.gemini_json_multimodal",
            ) as multimodal,
            patch(
                "app.services.quiz_extraction.get_settings",
                return_value=SimpleNamespace(
                    extraction_text_chunk_chars=18000,
                    extraction_chunk_concurrency=4,
                ),
            ),
        ):
            result = _extract_document_content(content=b"%PDF", ext="pdf")

        self.assertEqual(result, expected)
        fallback.assert_called_once()
        multimodal.assert_not_called()

    def test_scanned_pdf_uses_multimodal_gemini(self) -> None:
        # No extractable text (a scanned image PDF) -> Gemini vision.
        with (
            patch(
                "app.services.quiz_extraction.extract_text",
                return_value="",
            ),
            patch(
                "app.services.quiz_extraction.gemini_json_multimodal",
                return_value={"questions": []},
            ) as multimodal,
        ):
            result = _extract_document_content(content=b"%PDF", ext="pdf")

        self.assertEqual(result, ({"questions": []}, "gemini-vision"))
        multimodal.assert_called_once()

    def test_image_uses_multimodal_gemini(self) -> None:
        # Images can only be read by vision.
        with patch(
            "app.services.quiz_extraction.gemini_json_multimodal",
            return_value={"questions": []},
        ) as multimodal:
            result = _extract_document_content(content=b"\x89PNG", ext="png")

        self.assertEqual(result, ({"questions": []}, "gemini-vision"))
        multimodal.assert_called_once()

    def test_large_text_is_chunked_and_deduped(self) -> None:
        # A 120-150 page document must be split into several bounded calls, and
        # questions repeated across chunk boundaries must be de-duplicated.
        big_text = "\n\n".join(f"Paragraph {i} " * 40 for i in range(500))
        self.assertGreater(len(big_text), 18000)
        per_chunk = (
            {
                "questions": [
                    {"question_text": "Shared question one"},
                    {"question_text": "Shared question two"},
                ]
            },
            "gemini",
        )
        with (
            patch(
                "app.services.quiz_extraction.extract_text",
                return_value=big_text,
            ),
            patch(
                "app.services.quiz_extraction.complete_json_with_fallback",
                return_value=per_chunk,
            ) as fallback,
            patch(
                "app.services.quiz_extraction.get_settings",
                return_value=SimpleNamespace(
                    extraction_text_chunk_chars=18000,
                    extraction_chunk_concurrency=4,
                ),
            ),
        ):
            raw, provider = _extract_document_content(content=b"docx", ext="docx")

        self.assertGreater(fallback.call_count, 1)  # actually chunked
        self.assertEqual(len(raw["questions"]), 2)  # deduped across chunks
        self.assertIn("chunked", provider)


class ExtractionEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_upload_consumes_rate_limit_and_starts_extraction(self) -> None:
        upload = UploadFile(filename="quiz.pdf", file=io.BytesIO(b"%PDF-1.7\nquiz"))
        extracted = {"quiz_set_id": "quiz-1"}
        with (
            patch("app.api.extraction.get_service_client", return_value=_DocumentService()),
            patch("app.api.extraction.upload_bytes"),
            patch("app.api.extraction.enforce_ai_rate_limit") as enforce,
            patch(
                "app.api.extraction.get_settings",
                return_value=SimpleNamespace(rate_limit_quiz_extraction_per_hour=7),
            ),
            patch(
                "app.api.extraction.run_in_threadpool",
                new=AsyncMock(return_value=extracted),
            ),
        ):
            result = await extract_quiz_endpoint(
                file=upload,
                subject_id="subject-1",
                chapter_id="chapter-1",
                force=False,
                profile=profile(),
            )

        self.assertEqual(result, extracted)
        self.assertEqual(enforce.call_args.kwargs["endpoint"], "quiz_extraction")
        self.assertEqual(enforce.call_args.kwargs["hourly_limit"], 7)

    async def test_renamed_invalid_file_is_rejected_before_storage(self) -> None:
        upload = UploadFile(filename="quiz.pdf", file=io.BytesIO(b"plain text"))
        with patch("app.api.extraction.upload_bytes") as store:
            with self.assertRaises(HTTPException) as caught:
                await extract_quiz_endpoint(
                    file=upload,
                    subject_id="subject-1",
                    chapter_id="chapter-1",
                    force=False,
                    profile=profile(),
                )

        self.assertEqual(caught.exception.status_code, 400)
        store.assert_not_called()


class ExtractionMigrationTests(unittest.TestCase):
    def test_migration_numbers_are_unique(self) -> None:
        root = Path(__file__).resolve().parents[2]
        numbered: dict[str, list[str]] = {}
        for path in (root / "migrations").glob("migration-*.sql"):
            number = path.name.split("-", 2)[1]
            numbered.setdefault(number, []).append(path.name)
        duplicates = {
            number: names for number, names in numbered.items() if len(names) > 1
        }
        self.assertEqual(duplicates, {})

    def test_rate_limit_migration_allows_extraction_endpoint(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-19-quiz-extraction-rate-limit.sql"
        ).read_text().lower()
        self.assertIn("'quiz_extraction'", sql)
        self.assertIn("ai_rate_limits_endpoint_check", sql)
        self.assertIn(
            "create or replace function public.consume_ai_rate_limit", sql
        )
        self.assertIn("set search_path = ''", sql)

    def test_document_link_migration_and_schema_stay_in_sync(self) -> None:
        root = Path(__file__).resolve().parents[2]
        migration = (
            root / "migrations/migration-23-quiz-set-document-link.sql"
        ).read_text().lower()
        schema = (root / "migrations/schema.sql").read_text().lower()
        self.assertIn("alter table public.quiz_sets", migration)
        self.assertIn("references public.documents(id) on delete set null", migration)
        self.assertIn("idx_quizsets_tenant_document", migration)
        self.assertIn("document_id uuid references documents(id) on delete set null", schema)
        self.assertIn("idx_quizsets_tenant_document", schema)


if __name__ == "__main__":
    unittest.main()
