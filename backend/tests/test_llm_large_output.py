from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.llm.base import LLMError
from app.services.llm.structured import _deepseek_json_large

MODULE = "app.services.llm.structured"
SETTINGS = SimpleNamespace(
    deepseek_base_url="https://api.deepseek.example",
    deepseek_model="deepseek-chat",
    deepseek_api_key="test-key",
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


if __name__ == "__main__":
    unittest.main()
