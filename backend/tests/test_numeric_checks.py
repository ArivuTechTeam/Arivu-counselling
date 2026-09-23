from __future__ import annotations

import unittest
from decimal import Decimal

from app.services.numeric_checks import check_answer, recompute


class CalculatorCorrectnessTests(unittest.TestCase):
    def test_simple_interest(self):
        # SI = P*R*T/100 = 1000*5*2/100 = 100
        self.assertEqual(recompute("simple_interest", {"principal": 1000, "rate": 5, "time": 2}), Decimal(100))

    def test_compound_interest(self):
        # CI = 1000*(1.1)^2 - 1000 = 210
        self.assertEqual(recompute("compound_interest", {"principal": 1000, "rate": 10, "time": 2}), Decimal(210))

    def test_compound_interest_rejects_non_integer_periods(self):
        self.assertIsNone(recompute("compound_interest", {"principal": 1000, "rate": 10, "time": 2.5}))

    def test_straight_line_depreciation(self):
        # (10000 - 1000)/5 = 1800
        self.assertEqual(recompute("straight_line_depreciation", {"cost": 10000, "salvage": 1000, "useful_life": 5}), Decimal(1800))

    def test_break_even_units(self):
        # 10000 / (50 - 30) = 500
        self.assertEqual(recompute("break_even_units", {"fixed_costs": 10000, "price_per_unit": 50, "variable_cost_per_unit": 30}), Decimal(500))

    def test_percentage(self):
        # 25/200*100 = 12.5
        self.assertEqual(recompute("percentage", {"part": 25, "whole": 200}), Decimal("12.5"))

    def test_ratio(self):
        self.assertEqual(recompute("ratio", {"numerator": 15, "denominator": 5}), Decimal(3))


class SafetyTests(unittest.TestCase):
    def test_unknown_family_is_none(self):
        self.assertIsNone(recompute("black_scholes", {"x": 1}))

    def test_missing_input_is_none(self):
        self.assertIsNone(recompute("simple_interest", {"principal": 1000, "rate": 5}))

    def test_division_by_zero_is_none(self):
        self.assertIsNone(recompute("percentage", {"part": 5, "whole": 0}))
        self.assertIsNone(recompute("break_even_units", {"fixed_costs": 1, "price_per_unit": 30, "variable_cost_per_unit": 30}))
        self.assertIsNone(recompute("ratio", {"numerator": 1, "denominator": 0}))

    def test_non_finite_or_unparseable_is_none(self):
        self.assertIsNone(recompute("simple_interest", {"principal": "abc", "rate": 5, "time": 2}))
        self.assertIsNone(recompute("simple_interest", {"principal": float("inf"), "rate": 5, "time": 2}))

    def test_inputs_not_a_dict_is_none(self):
        self.assertIsNone(recompute("simple_interest", ["not", "a", "dict"]))


class CheckAnswerTests(unittest.TestCase):
    SI = {"principal": 1000, "rate": 5, "time": 2}  # -> 100

    def test_ok_within_tolerance(self):
        self.assertEqual(check_answer("simple_interest", self.SI, 100), "ok")
        self.assertEqual(check_answer("simple_interest", self.SI, 100.005, tolerance="0.01"), "ok")

    def test_mismatch_flags_wrong_ai_math(self):
        self.assertEqual(check_answer("simple_interest", self.SI, 150), "mismatch")

    def test_unsupported_family_not_checked(self):
        self.assertEqual(check_answer("nope", {"x": 1}, 100), "not_checked")

    def test_bad_inputs_not_checked(self):
        self.assertEqual(check_answer("simple_interest", {"principal": 1000}, 100), "not_checked")

    def test_unparseable_expected_not_checked(self):
        self.assertEqual(check_answer("simple_interest", self.SI, "n/a"), "not_checked")


if __name__ == "__main__":
    unittest.main()
