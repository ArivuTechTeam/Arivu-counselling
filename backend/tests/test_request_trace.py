from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.lib.api_errors import PublicAPIError
from app.lib.request_trace import request_id_for_header
from app.main import safe_http_error


class RequestTraceTests(unittest.TestCase):
    def test_preserves_safe_client_request_id(self) -> None:
        request_id = "client-request_1234.trace"

        self.assertEqual(request_id_for_header(request_id), request_id)

    def test_generates_id_when_header_is_missing(self) -> None:
        request_id = request_id_for_header(None)

        self.assertEqual(len(request_id), 32)
        self.assertTrue(request_id.isalnum())

    def test_replaces_log_injection_and_oversized_values(self) -> None:
        unsafe_values = (
            "bad\nforged-log-line",
            "short",
            "x" * 65,
            "contains spaces",
        )

        for unsafe_value in unsafe_values:
            with self.subTest(unsafe_value=unsafe_value):
                generated = request_id_for_header(unsafe_value)
                self.assertNotEqual(generated, unsafe_value)
                self.assertEqual(len(generated), 32)

    def test_safe_5xx_detail_is_returned_with_request_id(self) -> None:
        request = SimpleNamespace(state=SimpleNamespace(request_id="request-123"))
        response = asyncio.run(
            safe_http_error(
                request,
                PublicAPIError(
                    status_code=503,
                    detail="The account service is temporarily unavailable.",
                ),
            )
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"account service is temporarily unavailable", response.body)
        self.assertIn(b"request-123", response.body)

    def test_unmarked_5xx_detail_remains_hidden(self) -> None:
        request = SimpleNamespace(state=SimpleNamespace(request_id="request-456"))
        response = asyncio.run(
            safe_http_error(
                request,
                HTTPException(status_code=500, detail="private database detail"),
            )
        )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"private database detail", response.body)
        self.assertIn(b"Please try again", response.body)


if __name__ == "__main__":
    unittest.main()
