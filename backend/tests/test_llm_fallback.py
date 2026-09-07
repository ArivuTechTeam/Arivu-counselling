from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.llm.base import LLMError
from app.services.llm.structured import complete_json_with_fallback


class _Provider:
    def __init__(self, name: str, result: str | None = None) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    def complete(self, _system_prompt: str, _user_prompt: str) -> str:
        self.calls += 1
        if self.result is None:
            raise LLMError(f"{self.name} unavailable")
        return self.result


class StructuredFallbackTests(unittest.TestCase):
    def test_deepseek_is_used_when_gemini_fails(self) -> None:
        gemini = _Provider("gemini")
        deepseek = _Provider("deepseek", '{"topics": ["Cash Flow"]}')

        with patch(
            "app.services.llm.get_providers", return_value=[gemini, deepseek]
        ):
            data, provider = complete_json_with_fallback("system", "user")

        self.assertEqual(data, {"topics": ["Cash Flow"]})
        self.assertEqual(provider, "deepseek")
        self.assertEqual(gemini.calls, 1)
        self.assertEqual(deepseek.calls, 1)

    def test_primary_success_does_not_call_fallback(self) -> None:
        gemini = _Provider("gemini", '{"explanation": "Because"}')
        deepseek = _Provider("deepseek", '{"explanation": "Fallback"}')

        with patch(
            "app.services.llm.get_providers", return_value=[gemini, deepseek]
        ):
            data, provider = complete_json_with_fallback("system", "user")

        self.assertEqual(data, {"explanation": "Because"})
        self.assertEqual(provider, "gemini")
        self.assertEqual(gemini.calls, 1)
        self.assertEqual(deepseek.calls, 0)

    def test_invalid_json_is_reported_as_llm_error(self) -> None:
        provider = _Provider("deepseek", "not-json")
        with patch("app.services.llm.get_providers", return_value=[provider]):
            with self.assertRaisesRegex(LLMError, "deepseek returned invalid JSON"):
                complete_json_with_fallback("system", "user")


if __name__ == "__main__":
    unittest.main()
