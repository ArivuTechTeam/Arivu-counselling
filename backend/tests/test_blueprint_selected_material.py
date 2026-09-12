from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.blueprint import (
    SelectedTopic,
    _generate_with_exact_mix,
    build_blueprint,
)
from app.services.llm.base import LLMError
from app.services.blueprint_prompts import (
    build_blueprint_system_prompt,
    build_blueprint_user_prompt,
)


class SelectedMaterialBlueprintTests(unittest.TestCase):
    def test_all_questions_are_allocated_to_selected_topics(self) -> None:
        blueprint = build_blueprint(
            [SelectedTopic(name="Late chapter", weight="high")],
            5,
            selected_only=True,
        )
        self.assertEqual(blueprint["topics"][0]["num_questions"], 5)
        self.assertEqual(blueprint["general"], 0)
        self.assertEqual(blueprint["total"], 5)

    def test_selected_only_prompts_do_not_request_rest_of_document(self) -> None:
        blueprint = {
            "topics": [{"name": "Late chapter", "weight": "high", "num_questions": 2}],
            "general": 0,
            "total": 2,
        }
        system = build_blueprint_system_prompt(
            ["mcq_single"], "mixed", "medium", selected_only_material=True
        )
        user = build_blueprint_user_prompt(
            "late source fact", blueprint, ["mcq_single"], "mixed", "medium",
            selected_only_material=True,
        )
        self.assertIn("ONLY the teacher-selected topics", system)
        self.assertNotIn("REST of the document", user)

    def test_more_selected_topics_than_questions_is_rejected(self) -> None:
        selected = [
            SelectedTopic(name="One", weight="high"),
            SelectedTopic(name="Two", weight="medium"),
        ]
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            build_blueprint(selected, 1)


def _question(kind: str, text: str) -> dict:
    options = (
        [{"id": "a", "text": "Yes"}, {"id": "b", "text": "No"}]
        if kind in {"mcq_single", "mcq_multi", "true_false"}
        else None
    )
    answer: object = "a"
    if kind == "mcq_multi":
        answer = ["a"]
    elif kind == "numerical":
        answer = {"value": 1, "tolerance": 0}
    elif kind == "fill_blank":
        answer = {"answers": ["one"]}
    return {
        "topic": "One",
        "type": kind,
        "question_text": text,
        "options": options,
        "correct_answer": answer,
        "explanation": "Because.",
        "difficulty": "medium",
        "marks": 1,
    }


class ExactQuestionMixTests(unittest.TestCase):
    @patch("app.services.blueprint.complete_json_with_fallback")
    def test_bad_first_mix_is_corrected_once(self, complete) -> None:
        complete.side_effect = [
            ({"questions": [_question("mcq_single", "Q1")]}, "gemini"),
            (
                {
                    "questions": [
                        _question("mcq_single", "Q1 corrected"),
                        _question("true_false", "Q2 corrected"),
                    ]
                },
                "deepseek",
            ),
        ]
        quiz, provider = _generate_with_exact_mix(
            "system", "user", {"mcq_single": 1, "true_false": 1}
        )
        self.assertEqual(provider, "deepseek")
        self.assertEqual(len(quiz.questions), 2)
        self.assertEqual(complete.call_count, 2)
        self.assertIn("CORRECTION REQUIRED", complete.call_args_list[1].args[0])

    @patch("app.services.blueprint.complete_json_with_fallback")
    def test_second_bad_mix_fails_without_persistence(self, complete) -> None:
        wrong = ({"questions": [_question("mcq_single", "Only one")]}, "gemini")
        complete.side_effect = [wrong, wrong]
        with self.assertRaisesRegex(LLMError, "question mix mismatch"):
            _generate_with_exact_mix(
                "system", "user", {"mcq_single": 1, "true_false": 1}
            )
        self.assertEqual(complete.call_count, 2)


if __name__ == "__main__":
    unittest.main()
