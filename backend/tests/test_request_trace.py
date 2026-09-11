from __future__ import annotations

import unittest

from app.lib.request_trace import request_id_for_header


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


if __name__ == "__main__":
    unittest.main()
