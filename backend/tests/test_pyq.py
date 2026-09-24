"""Knowledge base (PYQ/MTP/RTP): detection flag-gating, snapshot logic, grading.

Flag-off must be byte-identical: the extraction prompt is unchanged and no paper
columns are written.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import pyq_snapshot as snap
from app.services.pyq_snapshot import _content_hash, _is_answerable, snapshot_published_pyq
from app.services.extraction_prompts import EXTRACTION_SYSTEM, extraction_system
from app.services import quiz_extraction as qx


def _q(**kw):
    kw.setdefault("type", "mcq_single")
    kw.setdefault("options", [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}])
    kw.setdefault("correct_answer", "a")
    kw.setdefault("question_text", "Q?")
    kw.setdefault("explanation", None)
    kw.setdefault("marks", 1)
    return kw


class ContentHashTests(unittest.TestCase):
    def test_ignores_whitespace_and_case(self):
        a = _content_hash(_q(question_text="What is 2+2?"))
        b = _content_hash(_q(question_text="  what   is 2+2?  "))
        self.assertEqual(a, b)

    def test_distinguishes_different_content(self):
        a = _content_hash(_q(question_text="What is 2+2?"))
        b = _content_hash(_q(question_text="What is 3+3?"))
        self.assertNotEqual(a, b)


class CompletenessTests(unittest.TestCase):
    def test_valid_mcq_is_answerable(self):
        self.assertTrue(_is_answerable(_q()))

    def test_missing_answer_is_not_answerable(self):
        self.assertFalse(_is_answerable(_q(correct_answer=None)))


class PromptFlagGatingTests(unittest.TestCase):
    def test_off_is_byte_identical(self):
        self.assertEqual(extraction_system(False), EXTRACTION_SYSTEM)

    def test_paper_mode_adds_classification_fields(self):
        on = extraction_system(True)
        self.assertIn("PAPER ANALYSIS", on)
        self.assertIn("paper_type", on)
        self.assertIn("paper_source_note", on)
        for t in ("pyq", "mtp", "rtp"):
            self.assertIn(t, on)


class InsertFieldsTests(unittest.TestCase):
    def _q(self, **kw):
        base = dict(explanation="e", is_pyq=False, year=None, paper_type=None,
                    exam=None, paper_source_note=None, model_answer=None, answer_summary=None)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_off_only_prefixes_explanation_no_columns(self):
        q = self._q(explanation="Because.", is_pyq=True, year="2019")
        fields = qx.pyq_insert_fields(q, paper_mode=False)
        self.assertEqual(fields, {"explanation": "[PYQ 2019] Because."})
        self.assertNotIn("paper_type", fields)

    def test_paper_mode_writes_clean_explanation_and_columns(self):
        q = self._q(explanation="Because.", paper_type="mtp", year="2019", exam="CA", paper_source_note="header")
        fields = qx.pyq_insert_fields(q, paper_mode=True)
        self.assertEqual(fields["explanation"], "Because.")
        self.assertEqual(fields["paper_type"], "mtp")
        self.assertEqual(fields["paper_year"], "2019")
        self.assertEqual(fields["paper_exam"], "CA")
        self.assertEqual(fields["paper_source_note"], "header")

    def test_paper_mode_non_paper_leaves_type_null(self):
        fields = qx.pyq_insert_fields(self._q(), paper_mode=True)
        self.assertIsNone(fields["paper_type"])
        self.assertIsNone(fields["paper_year"])


class _Query:
    def __init__(self, inserted, deleted, result=None):
        self._inserted, self._deleted, self._result = inserted, deleted, result

    def select(self, *_a, **_k):
        return self

    def delete(self):
        self._deleted.append(True)
        return self

    def insert(self, row):
        self._inserted.append(row)
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self._result)


class _Service:
    def __init__(self, inserted, deleted, quiz_set):
        self._inserted, self._deleted, self._quiz_set = inserted, deleted, quiz_set

    def table(self, name):
        if name == "quiz_sets":
            return _Query(self._inserted, self._deleted, self._quiz_set)
        return _Query(self._inserted, self._deleted, None)


class SnapshotTests(unittest.TestCase):
    QUESTIONS = [
        _q(id="1", paper_type="pyq", paper_year="2019", paper_exam="CA", chapter_id="ch1", review_status="approved"),
        _q(id="2", paper_type=None, review_status="approved"),               # not a paper -> skip
        _q(id="3", paper_type="pyq", review_status="pending_review"),        # not approved -> skip
        _q(id="4", paper_type="pyq", review_status="approved", correct_answer=None),  # ungradeable -> skip
    ]

    def _run(self, enabled):
        inserted, deleted = [], []
        service = _Service(inserted, deleted, {"id": "qs1", "subject_id": "subj1", "document_id": "doc1"})
        with patch.object(snap, "get_settings", return_value=SimpleNamespace(paper_bank_enabled=enabled)), \
             patch.object(snap, "select_all", return_value=[{"id": "v1"}]), \
             patch.object(snap, "select_all_in", side_effect=[[{"question_id": "1"}, {"question_id": "2"}, {"question_id": "3"}, {"question_id": "4"}], self.QUESTIONS]):
            added = snapshot_published_pyq(service, "t1", "qs1", "actor1")
        return added, inserted

    def test_disabled_is_noop(self):
        added, inserted = self._run(False)
        self.assertEqual(added, 0)
        self.assertEqual(inserted, [])

    def test_only_approved_answerable_paper_snapshotted(self):
        added, inserted = self._run(True)
        self.assertEqual(added, 1)
        self.assertEqual(len(inserted), 1)
        row = inserted[0]
        self.assertEqual(row["origin_question_id"], "1")
        self.assertEqual(row["paper_type"], "pyq")
        self.assertEqual(row["subject_id"], "subj1")
        self.assertEqual(row["chapter_id"], "ch1")
        self.assertEqual(row["year"], "2019")
        self.assertEqual(row["exam"], "CA")
        self.assertIn("content_hash", row)


class DescriptiveTests(unittest.TestCase):
    def test_validation_accepts_descriptive_with_model_answer(self):
        from app.services.quiz_extraction import _validate_import_candidates
        raw = {"questions": [{
            "type": "descriptive", "question_text": "Explain the accrual concept.",
            "options": None, "correct_answer": None, "marks": 5,
            "model_answer": "Accrual means recognising income/expense when earned/incurred.",
            "answer_summary": "Recognise income when earned and expenses when incurred, not on cash.",
        }]}
        questions, summary = _validate_import_candidates(raw)
        self.assertEqual(summary["imported"], 1)
        q = questions[0]
        self.assertEqual(q.type, "descriptive")
        self.assertIsNotNone(q.correct_answer)  # placeholder set so NOT NULL column accepts it

    def test_validation_skips_descriptive_without_model_answer(self):
        from app.services.quiz_extraction import _validate_import_candidates
        raw = {"questions": [{
            "type": "descriptive", "question_text": "Explain X.",
            "options": None, "correct_answer": None, "marks": 5, "model_answer": None,
        }]}
        questions, summary = _validate_import_candidates(raw)
        self.assertEqual(summary["imported"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_is_answerable_descriptive(self):
        self.assertTrue(_is_answerable({"type": "descriptive", "answer_summary": "key points"}))
        self.assertFalse(_is_answerable({"type": "descriptive", "answer_summary": None, "model_answer": None}))


class DescriptiveGraderTests(unittest.TestCase):
    def _grade(self, coverage, student="my answer"):
        from app.services import descriptive_grader as dg
        items = [{"question_id": "q1", "answer_summary": "key points", "student_answer": student}]
        with patch.object(dg, "complete_json_with_fallback",
                          return_value=({"grades": [{"id": "q1", "coverage": coverage}]}, "deepseek")):
            return dg.grade_descriptive(items)["q1"]

    def test_pass_at_or_above_threshold(self):
        self.assertTrue(self._grade(90))
        self.assertTrue(self._grade(95))

    def test_fail_below_threshold(self):
        self.assertFalse(self._grade(89))

    def test_blank_answer_never_calls_ai(self):
        from app.services import descriptive_grader as dg
        items = [{"question_id": "q1", "answer_summary": "k", "student_answer": "  "}]
        with patch.object(dg, "complete_json_with_fallback", side_effect=AssertionError("should not call")):
            self.assertFalse(dg.grade_descriptive(items)["q1"])

    def test_ai_failure_marks_pending_not_raise(self):
        from app.services import descriptive_grader as dg
        items = [{"question_id": "q1", "answer_summary": "k", "student_answer": "ans"}]
        with patch.object(dg, "complete_json_with_fallback", side_effect=RuntimeError("down")):
            self.assertFalse(dg.grade_descriptive(items)["q1"])  # best-effort, no raise


if __name__ == "__main__":
    unittest.main()
