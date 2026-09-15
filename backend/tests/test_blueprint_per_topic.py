from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.api.quiz import BlueprintTopicIn, _resolve_blueprint_plan
from app.services.blueprint import SelectedTopic, build_blueprint
from app.services.blueprint_prompts import build_blueprint_user_prompt


class BuildBlueprintPerTopicTests(unittest.TestCase):
    def test_per_topic_counts_drive_allocation_and_total(self) -> None:
        selected = [
            SelectedTopic(name="Alpha", counts={"mcq_single": 2, "fill_blank": 1}),
            SelectedTopic(name="Beta", counts={"true_false": 3}),
        ]
        bp = build_blueprint(selected, total=6)
        self.assertEqual(bp["mode"], "per_topic")
        self.assertEqual(bp["general"], 0)
        self.assertEqual(bp["total"], 6)
        by_name = {t["name"]: t for t in bp["topics"]}
        self.assertEqual(by_name["Alpha"]["num_questions"], 3)
        self.assertEqual(by_name["Beta"]["counts"], {"true_false": 3})

    def test_zero_counts_are_dropped(self) -> None:
        bp = build_blueprint(
            [SelectedTopic(name="Alpha", counts={"mcq_single": 2, "numerical": 0})],
            total=2,
        )
        self.assertEqual(bp["topics"][0]["counts"], {"mcq_single": 2})
        self.assertEqual(bp["total"], 2)

    def test_no_counts_keeps_legacy_weight_behaviour(self) -> None:
        bp = build_blueprint(
            [SelectedTopic(name="Alpha", weight="high")], total=10
        )
        self.assertNotIn("mode", bp)  # legacy path
        self.assertEqual(bp["total"], 10)
        self.assertGreater(bp["general"], 0)  # 70/30 general coverage preserved


class BlueprintPromptPerTopicTests(unittest.TestCase):
    def test_prompt_lists_exact_per_topic_plan_and_no_general(self) -> None:
        bp = build_blueprint(
            [
                SelectedTopic(name="Alpha", counts={"mcq_single": 2}),
                SelectedTopic(name="Beta", counts={"true_false": 1}),
            ],
            total=3,
        )
        prompt = build_blueprint_user_prompt(
            "MATERIAL",
            bp,
            ["mcq_single", "true_false"],
            "mixed",
            "medium",
            {"mcq_single": 2, "true_false": 1},
            selected_only_material=True,
        )
        self.assertIn("PER-TOPIC PLAN", prompt)
        self.assertIn('Topic "Alpha"', prompt)
        self.assertIn("mcq_single: exactly 2", prompt)
        self.assertNotIn("GENERAL COVERAGE", prompt)


class ResolveBlueprintPlanTests(unittest.TestCase):
    def test_per_topic_request_aggregates_counts(self) -> None:
        topics = [
            BlueprintTopicIn(name="Alpha", counts={"mcq_single": 2, "true_false": 1}),
            BlueprintTopicIn(name="Beta", counts={"mcq_single": 1}),
        ]
        selected, aggregate, total, qtypes = _resolve_blueprint_plan(topics, {})
        self.assertEqual(total, 4)
        self.assertEqual(aggregate, {"mcq_single": 3, "true_false": 1})
        self.assertEqual(selected[0]["counts"], {"mcq_single": 2, "true_false": 1})
        self.assertCountEqual(qtypes, ["mcq_single", "true_false"])

    def test_legacy_request_uses_global_counts(self) -> None:
        topics = [BlueprintTopicIn(name="Alpha", weight="high")]
        selected, counts, total, qtypes = _resolve_blueprint_plan(
            topics, {"mcq_single": 5, "true_false": 0}
        )
        self.assertEqual(total, 5)
        self.assertEqual(counts, {"mcq_single": 5})
        self.assertEqual(selected[0]["name"], "Alpha")

    def test_per_topic_rejects_unknown_type(self) -> None:
        topics = [BlueprintTopicIn(name="Alpha", counts={"essay": 2})]
        with self.assertRaises(HTTPException) as raised:
            _resolve_blueprint_plan(topics, {})
        self.assertEqual(raised.exception.status_code, 400)

    def test_per_topic_rejects_empty_topic(self) -> None:
        topics = [BlueprintTopicIn(name="Alpha", counts={"mcq_single": 0})]
        with self.assertRaises(HTTPException) as raised:
            _resolve_blueprint_plan(topics, {})
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
