from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.document_profile import profile_document, profile_to_summary
from app.services.llm.base import LLMError

MOD = "app.services.document_profile"
PROFILE_SETTINGS = SimpleNamespace(generation_profile_max_chars=50_000)


class ProfileToSummaryTests(unittest.TestCase):
    def test_flattens_subject_and_summary(self) -> None:
        self.assertEqual(
            profile_to_summary({"subject": "Math", "summary": "Teaches algebra."}),
            "Math Teaches algebra.",
        )

    def test_handles_missing_or_empty(self) -> None:
        self.assertEqual(profile_to_summary(None), "")
        self.assertEqual(profile_to_summary({}), "")
        self.assertEqual(profile_to_summary({"subject": "Only subject"}), "Only subject")

    def test_includes_subject_neutral_content_signals(self) -> None:
        summary = profile_to_summary({
            "subject": "History",
            "language": "English",
            "chronology_signals": ["Treaty dates and political events"],
            "visual_dependencies": ["Map boundaries"],
            "supported_question_types": ["mcq_single", "true_false"],
        })
        self.assertIn("Treaty dates", summary)
        self.assertIn("Map boundaries", summary)
        self.assertIn("mcq_single", summary)


class ProfileDocumentTests(unittest.TestCase):
    def test_returns_subject_and_summary(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=PROFILE_SETTINGS), patch(
            f"{MOD}.complete_json_large",
            return_value=({"subject": "Python", "summary": "Teaches strings."}, "gemini"),
        ):
            p = profile_document("a real document about python strings")
        self.assertEqual(p, {"subject": "Python", "summary": "Teaches strings."})

    def test_blank_text_makes_no_call(self) -> None:
        with patch(f"{MOD}.complete_json_large") as call:
            self.assertEqual(profile_document("   "), {})
        call.assert_not_called()

    def test_llm_failure_degrades_to_empty(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=PROFILE_SETTINGS), patch(
            f"{MOD}.complete_json_large", side_effect=LLMError("boom")
        ):
            self.assertEqual(profile_document("text"), {})

    def test_empty_result_returns_empty(self) -> None:
        with patch(f"{MOD}.get_settings", return_value=PROFILE_SETTINGS), patch(
            f"{MOD}.complete_json_large",
            return_value=({"subject": "", "summary": ""}, "gemini"),
        ):
            self.assertEqual(profile_document("text"), {})


if __name__ == "__main__":
    unittest.main()
