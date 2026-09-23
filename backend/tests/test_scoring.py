from __future__ import annotations

import unittest

from app.services.grading import grade_answer
from app.services.scoring import (
    Outcome,
    normalize_policy,
    score,
    total_from_outcomes,
)

# One question per type, with a correct, a wrong, and a blank answer.
CASES = [
    ({"type": "mcq_single", "marks": 2, "correct_answer": "a"}, "a", "b"),
    ({"type": "true_false", "marks": 1, "correct_answer": "true"}, "true", "false"),
    ({"type": "numerical", "marks": 3, "correct_answer": {"value": 10, "tolerance": 0.5}}, 10.2, 20),
    ({"type": "fill_blank", "marks": 1, "correct_answer": {"answers": ["paris"]}}, "Paris", "london"),
    ({"type": "mcq_multi", "marks": 2, "correct_answer": ["a", "b"]}, ["a", "b"], ["a"]),
]


class DefaultPolicyMatchesLegacyTests(unittest.TestCase):
    """The default policy must reproduce grade_answer exactly for every type."""

    def test_default_equals_grade_answer(self):
        for question, correct_ans, wrong_ans in CASES:
            marks = float(question["marks"])
            with self.subTest(type=question["type"]):
                # correct
                gi, ga = grade_answer(question, correct_ans)
                out = score(question, correct_ans, None)
                self.assertTrue(gi)
                self.assertEqual(out.state, "correct")
                self.assertEqual(out.awarded, ga)
                self.assertEqual(out.awarded, marks)
                # wrong
                gi, ga = grade_answer(question, wrong_ans)
                out = score(question, wrong_ans, None)
                self.assertFalse(gi)
                self.assertEqual(out.state, "wrong")
                self.assertEqual(out.awarded, ga)
                self.assertEqual(out.awarded, 0.0)
                # blank
                out = score(question, None, None)
                self.assertEqual(out.state, "blank")
                self.assertEqual(out.awarded, 0.0)


class NegativeMarkingTests(unittest.TestCase):
    Q = {"type": "mcq_single", "marks": 2, "correct_answer": "a"}

    def test_absolute_penalty_on_wrong_answered(self):
        out = score(self.Q, "b", {"wrong_penalty": 0.25})
        self.assertEqual(out, Outcome("wrong", -0.25))

    def test_blank_is_never_penalised(self):
        out = score(self.Q, None, {"wrong_penalty": 0.25})
        self.assertEqual(out, Outcome("blank", 0.0))

    def test_correct_unaffected(self):
        out = score(self.Q, "a", {"wrong_penalty": 0.25})
        self.assertEqual(out, Outcome("correct", 2.0))

    def test_fractional_penalty(self):
        out = score(self.Q, "b", {"wrong_penalty": 0.25, "penalty_is_fraction": True})
        self.assertEqual(out.awarded, -0.5)  # 0.25 * 2 marks


class MrmPartialTests(unittest.TestCase):
    Q = {"type": "mcq_multi", "marks": 3, "correct_answer": ["a", "b", "c"]}
    P = {"multi_mode": "mrm_partial"}

    def test_all_correct_full(self):
        self.assertEqual(score(self.Q, ["a", "b", "c"], self.P), Outcome("correct", 3.0))

    def test_some_correct_partial(self):
        self.assertEqual(score(self.Q, ["a", "b"], self.P), Outcome("partial", 2.0))

    def test_wrong_selection_cancels(self):
        # 1 correct - 1 wrong = 0 net -> wrong.
        self.assertEqual(score(self.Q, ["a", "x"], self.P), Outcome("wrong", 0.0))

    def test_one_correct_partial(self):
        self.assertEqual(score(self.Q, ["a"], self.P), Outcome("partial", 1.0))

    def test_all_or_nothing_default_is_unchanged(self):
        # Without mrm_partial, mcq_multi stays all-or-nothing via grade_answer.
        self.assertEqual(score(self.Q, ["a", "b"], None), Outcome("wrong", 0.0))


class DescriptiveAndTotalsTests(unittest.TestCase):
    def test_descriptive_needs_manual(self):
        out = score({"type": "descriptive", "marks": 10, "correct_answer": None}, "essay text", None)
        self.assertEqual(out, Outcome("needs_manual", 0.0))

    def test_total_clamps_when_policy_clamps(self):
        outs = [Outcome("wrong", -0.25), Outcome("wrong", -0.25)]
        self.assertEqual(total_from_outcomes(outs, {"wrong_penalty": 0.25}), 0.0)

    def test_total_can_go_negative_without_clamp(self):
        outs = [Outcome("correct", 1.0), Outcome("wrong", -2.0)]
        self.assertEqual(total_from_outcomes(outs, {"clamp_negative_total": False}), -1.0)

    def test_normalize_policy_none_is_default(self):
        self.assertEqual(normalize_policy(None), normalize_policy({}))


class NumericContractTests(unittest.TestCase):
    def _q(self, value, tol=0):
        return {"type": "numerical", "marks": 1,
                "correct_answer": {"value": value, "tolerance": tol}}

    def _state(self, q, ans, numeric):
        return score(q, ans, {"numeric": numeric}).state

    def test_tolerance(self):
        q = self._q(100)
        self.assertEqual(self._state(q, 100.4, {"tolerance": 0.5}), "correct")
        self.assertEqual(self._state(q, 100.6, {"tolerance": 0.5}), "wrong")

    def test_rounding_to_two_decimals(self):
        q = self._q(10.00)
        self.assertEqual(self._state(q, 10.004, {"decimals": 2}), "correct")  # -> 10.00
        self.assertEqual(self._state(q, 10.006, {"decimals": 2}), "wrong")    # -> 10.01

    def test_floor_rounding(self):
        q = self._q(10)
        self.assertEqual(self._state(q, 10.9, {"decimals": 0, "rounding": "floor"}), "correct")

    def test_non_finite_or_unparseable_is_wrong(self):
        q = self._q(5)
        self.assertEqual(self._state(q, "abc", {"decimals": 2}), "wrong")
        self.assertEqual(self._state(q, float("inf"), {"decimals": 2}), "wrong")

    def test_no_contract_uses_legacy_tolerance(self):
        # Without a numeric contract, numerical still grades via grade_answer.
        q = self._q(10, tol=0.5)
        self.assertEqual(score(q, 10.2, None).state, "correct")
        self.assertEqual(score(q, 20, None).state, "wrong")


if __name__ == "__main__":
    unittest.main()
