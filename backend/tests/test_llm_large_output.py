from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.llm.base import LLMError
from app.services.llm.structured import (
    _deepseek_json_large,
    _gemini_json_large,
)
from app.services.llm.gemini_http import _gemini_unavailable_models

MODULE = "app.services.llm.structured"
SETTINGS = SimpleNamespace(
    deepseek_base_url="https://api.deepseek.example",
    deepseek_model="deepseek-chat",
    deepseek_api_key="test-key",
    generation_large_request_timeout_seconds=600,
)


class DeepSeekLargeOutputTests(unittest.TestCase):
    def test_valid_shorter_json_is_accepted(self) -> None:
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": '{"topics": []}'},
                }]
            },
        )
        with patch(f"{MODULE}.get_settings", return_value=SETTINGS), patch(
            f"{MODULE}.httpx.post", return_value=response
        ) as post:
            result = _deepseek_json_large("system", "user", max_tokens=8192)
        self.assertEqual(result, {"topics": []})
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 8192)
        self.assertEqual(
            post.call_args.kwargs["json"]["thinking"], {"type": "disabled"}
        )
        self.assertEqual(post.call_args.kwargs["timeout"], 600)

    def test_finish_reason_length_is_an_explicit_failure(self) -> None:
        response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"topics": ['},
                }]
            },
        )
        with patch(f"{MODULE}.get_settings", return_value=SETTINGS), patch(
            f"{MODULE}.httpx.post", return_value=response
        ):
            with self.assertRaisesRegex(LLMError, "output-token limit"):
                _deepseek_json_large("system", "user", max_tokens=8192)


class GeminiModelFallbackTests(unittest.TestCase):
    def test_model_404_retries_configured_gemini_fallback(self) -> None:
        _gemini_unavailable_models.clear()
        settings = SimpleNamespace(
            gemini_base_url="https://generativelanguage.googleapis.test/v1beta",
            gemini_api_key="test-key",
            gemini_fallback_model="gemini-current",
            generation_large_request_timeout_seconds=600,
        )
        missing = httpx.Response(
            404,
            request=httpx.Request("POST", "https://example.test/missing"),
        )
        success = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"topics": []}'}]},
                }]
            },
        )
        with patch(f"{MODULE}.get_settings", return_value=settings), patch(
            "app.services.llm.gemini_http.httpx.post", side_effect=[missing, success]
        ) as post:
            result = _gemini_json_large(
                "system", "user", model="gemini-retired", max_output_tokens=100
            )

        self.assertEqual(result, {"topics": []})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["timeout"], 600)
        self.assertIn("gemini-retired:generateContent", post.call_args_list[0].args[0])
        self.assertIn("gemini-current:generateContent", post.call_args_list[1].args[0])

    def test_known_missing_model_is_skipped_on_later_calls(self) -> None:
        _gemini_unavailable_models.clear()
        settings = SimpleNamespace(
            gemini_base_url="https://generativelanguage.googleapis.test/v1beta",
            gemini_api_key="test-key",
            gemini_fallback_model="gemini-current",
            generation_large_request_timeout_seconds=600,
        )
        missing = httpx.Response(
            404,
            request=httpx.Request("POST", "https://example.test/missing"),
        )
        success = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"topics": []}'}]},
                }]
            },
        )
        with patch(f"{MODULE}.get_settings", return_value=settings), patch(
            "app.services.llm.gemini_http.httpx.post",
            side_effect=[missing, success, success],
        ) as post:
            _gemini_json_large(
                "system", "user", model="gemini-retired", max_output_tokens=100
            )
            _gemini_json_large(
                "system", "user", model="gemini-retired", max_output_tokens=100
            )

        self.assertEqual(post.call_count, 3)
        self.assertIn("gemini-current:generateContent", post.call_args_list[2].args[0])


if __name__ == "__main__":
    unittest.main()
