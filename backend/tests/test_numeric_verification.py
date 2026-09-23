from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import question_verification as mod


class _Check:
    def __init__(self, status="verified"):
        self.status = status
        self.warnings: list[str] = []

    def flag(self, status, warning):
        self.status = status
        self.warnings.append(warning)


# A generated simple-interest question whose stated answer (100) is correct.
def _q(value, family="simple_interest", inputs=None, q_type="numerical"):
    return {
        "type": q_type,
        "correct_answer": {"value": value, "tolerance": 0.5},
        "calc": {"family": family, "inputs": inputs or {"principal": 1000, "rate": 5, "time": 2}},
    }


def _apply(checks, questions, *, enabled):
    with patch.object(mod, "get_settings",
                      return_value=SimpleNamespace(commerce_pack_enabled=enabled)):
        mod._apply_numeric_checks(checks, questions)


class NumericVerificationTests(unittest.TestCase):
    def test_flag_off_is_noop(self):
        checks = [_Check()]
        _apply(checks, [_q(999)], enabled=False)  # wrong answer, but flag off
        self.assertEqual(checks[0].status, "verified")

    def test_correct_answer_passes(self):
        checks = [_Check()]
        _apply(checks, [_q(100)], enabled=True)  # SI = 100, correct
        self.assertEqual(checks[0].status, "verified")

    def test_wrong_ai_math_routed_to_review(self):
        checks = [_Check()]
        _apply(checks, [_q(150)], enabled=True)  # SI is 100, not 150
        self.assertEqual(checks[0].status, "needs_teacher_review")
        self.assertTrue(any("numeric_check_failed" in w for w in checks[0].warnings))

    def test_no_calc_is_untouched(self):
        checks = [_Check()]
        q = _q(999)
        del q["calc"]
        _apply(checks, [q], enabled=True)
        self.assertEqual(checks[0].status, "verified")

    def test_non_numerical_untouched(self):
        checks = [_Check()]
        _apply(checks, [_q(999, q_type="mcq_single")], enabled=True)
        self.assertEqual(checks[0].status, "verified")

    def test_unsupported_status_not_overridden(self):
        checks = [_Check(status="unsupported")]
        _apply(checks, [_q(150)], enabled=True)  # even though math is wrong
        self.assertEqual(checks[0].status, "unsupported")


if __name__ == "__main__":
    unittest.main()
