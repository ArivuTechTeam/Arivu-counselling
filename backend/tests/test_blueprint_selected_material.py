from __future__ import annotations

import unittest

from app.services.blueprint import SelectedTopic, build_blueprint
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


if __name__ == "__main__":
    unittest.main()
