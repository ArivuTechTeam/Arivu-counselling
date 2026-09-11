from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.attempt_timing import (
    deadline_state,
    is_answered,
    pacing_seconds,
    taking_questions,
    timing_payload,
    effective_time_limit_minutes,
)


class AttemptTimingTests(unittest.TestCase):
    def test_untimed_pacing_uses_question_type_defaults(self) -> None:
        questions = [
            {"id": "tf", "type": "true_false"},
            {"id": "single", "type": "mcq_single"},
            {"id": "fill", "type": "fill_blank"},
            {"id": "multi", "type": "mcq_multi"},
            {"id": "number", "type": "numerical"},
        ]
        self.assertEqual(pacing_seconds(questions, None), [45, 60, 75, 90, 120])

    def test_timed_pacing_preserves_total_and_relative_effort(self) -> None:
        questions = [
            {"id": "single", "type": "mcq_single"},
            {"id": "number", "type": "numerical"},
            {"id": "multi", "type": "mcq_multi"},
        ]
        budgets = pacing_seconds(questions, 600)
        self.assertEqual(sum(budgets), 600)
        self.assertGreater(budgets[1], budgets[0])
        self.assertGreater(budgets[2], budgets[0])
        enriched = taking_questions(questions, 10)
        self.assertEqual(sum(q["suggested_seconds"] for q in enriched), 600)

    def test_missing_config_derives_a_rounded_up_overall_limit(self) -> None:
        questions = [
            {"type": "mcq_single"},
            {"type": "numerical"},
            {"type": "true_false"},
        ]
        self.assertEqual(effective_time_limit_minutes(questions), 4)
        self.assertEqual(effective_time_limit_minutes(questions, 12), 12.0)

    def test_deadline_distinguishes_expiry_from_network_grace(self) -> None:
        started = "2026-09-10T10:00:00Z"
        at_five_seconds = deadline_state(
            started,
            60,
            now=datetime(2026, 9, 10, 11, 0, 5, tzinfo=timezone.utc),
        )
        at_eleven_seconds = deadline_state(
            started,
            60,
            now=datetime(2026, 9, 10, 11, 0, 11, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(at_five_seconds)
        self.assertTrue(at_five_seconds.reached)
        self.assertFalse(at_five_seconds.beyond_grace)
        self.assertTrue(at_eleven_seconds.beyond_grace)

    def test_invalid_or_untimed_values_produce_no_deadline(self) -> None:
        self.assertIsNone(deadline_state("not-a-date", 10))
        self.assertIsNone(deadline_state("2026-09-10T10:00:00Z", 0))
        self.assertEqual(timing_payload(None, None), {})

    def test_answer_completeness_treats_blank_values_as_unanswered(self) -> None:
        for value in (None, "", []):
            with self.subTest(value=value):
                self.assertFalse(is_answered(value))
        for value in (0, False, "A", ["A"]):
            with self.subTest(value=value):
                self.assertTrue(is_answered(value))


if __name__ == "__main__":
    unittest.main()
