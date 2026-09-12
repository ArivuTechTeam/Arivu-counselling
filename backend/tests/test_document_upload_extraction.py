from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from app.api.documents import upload_document
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, service: "_Service") -> None:
        self.service = service
        self.payload: dict | None = None

    def insert(self, payload: dict):
        self.payload = payload
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        assert self.payload is not None
        if "storage_path" in self.payload:
            return SimpleNamespace(
                data=[{
                    **self.payload,
                    "id": "document-1",
                    "created_at": "2026-09-12T00:00:00+00:00",
                }]
            )
        self.service.updates.append(self.payload)
        return SimpleNamespace(data=[self.payload])


class _Service:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def table(self, _name: str) -> _Query:
        return _Query(self)


def _teacher() -> CurrentProfile:
    return CurrentProfile(user_id="teacher-1", tenant_id="tenant-1", role="teacher")


class DocumentUploadExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_scanned_pdf_is_marked_failed_with_actionable_guidance(self) -> None:
        service = _Service()
        upload = UploadFile(filename="scan.pdf", file=io.BytesIO(b"pdf bytes"))

        with patch("app.api.documents.upload_bytes"), patch(
            "app.api.documents.get_service_client", return_value=service
        ), patch("app.api.documents.extract_text", return_value="page 1"):
            with self.assertRaises(HTTPException) as raised:
                await upload_document(upload, _teacher())

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("scanned document", raised.exception.detail)
        self.assertIn("Extract Quiz", raised.exception.detail)
        self.assertEqual(service.updates[-1]["status"], "failed")
        self.assertEqual(service.updates[-1]["error_message"], raised.exception.detail)

    async def test_text_pdf_over_threshold_is_completed(self) -> None:
        service = _Service()
        upload = UploadFile(filename="typed.pdf", file=io.BytesIO(b"pdf bytes"))

        with patch("app.api.documents.upload_bytes"), patch(
            "app.api.documents.get_service_client", return_value=service
        ), patch("app.api.documents.extract_text", return_value="x" * 200):
            result = await upload_document(upload, _teacher())

        self.assertEqual(result.document.status, "completed")
        self.assertEqual(result.char_count, 200)
        self.assertEqual(service.updates[-1], {"status": "completed"})


if __name__ == "__main__":
    unittest.main()
