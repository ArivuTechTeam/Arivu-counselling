"""Phase 6.4: extended objective question types (assertion_reason, mrm, matching).

Validates shape rules, deterministic grading, and policy-aware scoring for the
three new auto-graded types. The 5 existing types must be unaffected.
"""

from __future__ import annotations

import unittest

from app.services.grading import grade_answer
from app.services.question_validation import validate_question_answer_shape
from app.services.scoring import CORRECT, PARTIAL, WRONG, BLANK, score

# --- fixtures -----------------------------------------------------------------

AR_OPTIONS = [
    {"id": "a", "text": "Both A and R true and R explains A"},
    {"id": "b", "text": "Both A and R true but R does not explain A"},
    {"id": "c", "text": "A true, R false"},
    {"id": "d", "text": "A false, R true"},
]

MRM_OPTIONS = [
    {"id": "a", "text": "Asset"},
    {"id": "b", "text": "Liability"},
    {"id": "c", "text": "Equity"},
    {"id": "d", "text": "Expense"},
]

MATCH_OPTIONS = [
    {"id": "l1", "side": "left", "text": "Cash"},
    {"id": "l2", "side": "left", "text": "Rent paid"},
    {"id": "r1", "side": "right", "text": "Asset"},
    {"id": "r2", "side": "right", "text": "Expense"},
    {"id": "r3", "side": "right", "text": "Income (distractor)"},
]
MATCH_CORRECT = {"pairs": {"l1": "r1", "l2": "r2"}}


def q(**kw):
    kw.setdefault("marks", 1)
    return kw


# --- validation ---------------------------------------------------------------

class ValidationTests(unittest.TestCase):
    def test_assertion_reason_ok(self):
        validate_question_answer_shape("assertion_reason", AR_OPTIONS, "a")

    def test_assertion_reason_bad_id(self):
        with self.assertRaises(ValueError):
            validate_question_answer_shape("assertion_reason", AR_OPTIONS, "z")

    def test_mrm_ok(self):
        validate_question_answer_shape("mrm", MRM_OPTIONS, ["a", "c"])

    def test_mrm_requires_list(self):
        with self.assertRaises(ValueError):
            validate_question_answer_shape("mrm", MRM_OPTIONS, "a")

    def test_mrm_ids_must_exist(self):
        with self.assertRaises(ValueError):
            validate_question_answer_shape("mrm", MRM_OPTIONS, ["a", "z"])

    def test_matching_ok(self):
        validate_question_answer_shape("matching", MATCH_OPTIONS, MATCH_CORRECT)

    def test_matching_needs_every_left_paired(self):
        with self.assertRaises(ValueError):
            validate_question_answer_shape("matching", MATCH_OPTIONS, {"pairs": {"l1": "r1"}})

    def test_matching_pair_must_point_to_real_right(self):
        with self.assertRaises(ValueError):
            validate_question_answer_shape(
                "matching", MATCH_OPTIONS, {"pairs": {"l1": "r1", "l2": "zzz"}}
            )

    def test_matching_side_required(self):
        bad = [{"id": "l1", "text": "x"}, {"id": "r1", "side": "right", "text": "y"}]
        with self.assertRaises(ValueError):
            validate_question_answer_shape("matching", bad, {"pairs": {"l1": "r1"}})


# --- deterministic grading (grade_answer / full-zero path) --------------------

class GradeAnswerTests(unittest.TestCase):
    def test_assertion_reason_correct(self):
        self.assertEqual(grade_answer(q(type="assertion_reason", correct_answer="a"), "a"), (True, 1.0))

    def test_assertion_reason_wrong(self):
        self.assertEqual(grade_answer(q(type="assertion_reason", correct_answer="a"), "b"), (False, 0.0))

    def test_mrm_all_or_nothing_binary(self):
        item = q(type="mrm", correct_answer=["a", "c"])
        self.assertEqual(grade_answer(item, ["a", "c"]), (True, 1.0))
        self.assertEqual(grade_answer(item, ["a"]), (False, 0.0))

    def test_matching_all_pairs_binary(self):
        item = q(type="matching", correct_answer=MATCH_CORRECT)
        self.assertEqual(grade_answer(item, {"l1": "r1", "l2": "r2"}), (True, 1.0))
        self.assertEqual(grade_answer(item, {"l1": "r1", "l2": "r3"}), (False, 0.0))


# --- policy-aware scoring (partial credit) ------------------------------------

class ScoringTests(unittest.TestCase):
    def test_mrm_partial_credit_by_default(self):
        item = q(type="mrm", correct_answer=["a", "c"], marks=2)
        # 1 of 2 correct, 0 wrong -> half marks, PARTIAL (no policy needed for mrm)
        out = score(item, ["a"])
        self.assertEqual(out.state, PARTIAL)
        self.assertEqual(out.awarded, 1.0)

    def test_mrm_full_and_wrong(self):
        item = q(type="mrm", correct_answer=["a", "c"], marks=2)
        self.assertEqual(score(item, ["a", "c"]).state, CORRECT)
        # one correct minus one wrong -> net 0 -> WRONG
        self.assertEqual(score(item, ["a", "b"]).state, WRONG)

    def test_matching_partial_credit(self):
        item = q(type="matching", correct_answer=MATCH_CORRECT, marks=2)
        out = score(item, {"l1": "r1", "l2": "r3"})  # 1 of 2 right
        self.assertEqual(out.state, PARTIAL)
        self.assertEqual(out.awarded, 1.0)

    def test_matching_full(self):
        item = q(type="matching", correct_answer=MATCH_CORRECT, marks=2)
        self.assertEqual(score(item, {"l1": "r1", "l2": "r2"}).state, CORRECT)

    def test_empty_matching_is_blank_not_wrong(self):
        item = q(type="matching", correct_answer=MATCH_CORRECT)
        self.assertEqual(score(item, {}).state, BLANK)

    def test_assertion_reason_scores_like_single_choice(self):
        item = q(type="assertion_reason", correct_answer="a")
        self.assertEqual(score(item, "a").state, CORRECT)
        self.assertEqual(score(item, "b").state, WRONG)
        self.assertEqual(score(item, None).state, BLANK)


if __name__ == "__main__":
    unittest.main()
