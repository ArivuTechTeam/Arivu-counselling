from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.services.llm as router
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

    def test_invalid_primary_json_uses_valid_fallback(self) -> None:
        deepseek = _Provider("deepseek", "not-json")
        gemini = _Provider("gemini", '{"topics": ["Networks"]}')
        with patch(
            "app.services.llm.get_providers", return_value=[deepseek, gemini]
        ):
            data, provider = complete_json_with_fallback(
                "system", "user", preferred_provider="deepseek"
            )
        self.assertEqual(data, {"topics": ["Networks"]})
        self.assertEqual(provider, "gemini")


class StageRouterTests(unittest.TestCase):
    def test_raw_router_falls_back_on_invalid_json(self) -> None:
        deepseek = _Provider("deepseek", "not-json")
        gemini = _Provider("gemini", '{"questions": []}')
        with patch.object(router, "get_providers", return_value=[deepseek, gemini]):
            raw, provider = router.complete_with_fallback(
                "system", "user", preferred_provider="deepseek"
            )
        self.assertEqual(raw, '{"questions": []}')
        self.assertEqual(provider, "gemini")

    def test_preferred_deepseek_is_first_when_both_keys_exist(self) -> None:
        settings = SimpleNamespace(
            deepseek_api_key="deepseek-key",
            gemini_api_key="gemini-key",
            ai_fallback_provider="gemini",
        )
        with patch.object(router, "get_settings", return_value=settings):
            providers = router.get_providers("deepseek")
        self.assertEqual([provider.name for provider in providers], ["deepseek", "gemini"])

    def test_missing_preferred_key_uses_available_fallback(self) -> None:
        settings = SimpleNamespace(
            deepseek_api_key="",
            gemini_api_key="gemini-key",
            ai_fallback_provider="gemini",
        )
        with patch.object(router, "get_settings", return_value=settings):
            providers = router.get_providers("deepseek")
        self.assertEqual([provider.name for provider in providers], ["gemini"])


if __name__ == "__main__":
    unittest.main()
