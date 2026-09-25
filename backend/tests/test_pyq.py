"""Knowledge base (PYQ/MTP/RTP): detection flag-gating, snapshot logic, grading.

Flag-off must be byte-identical: the extraction prompt is unchanged and no paper
columns are written.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api import pyq as papers
from app.lib.auth import CurrentProfile

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
    def __init__(self, result=None):
        self._result = result

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self._result)


class _Service:
    def __init__(self, quiz_set, *, rpc_error=None):
        self._quiz_set = quiz_set
        self.rpc_error = rpc_error
        self.rpc_calls = []

    def table(self, name):
        if name == "quiz_sets":
            return _Query(self._quiz_set)
        raise AssertionError("Snapshot must not write tables outside its RPC")

    def rpc(self, name, payload):
        self.rpc_calls.append((name, payload))
        if self.rpc_error:
            raise self.rpc_error
        return _Query(len(payload["p_rows"]))


class SnapshotTests(unittest.TestCase):
    QUESTIONS = [
        _q(id="1", paper_type="pyq", paper_year="2019", paper_exam="CA", chapter_id="ch1", review_status="approved"),
        _q(id="2", paper_type=None, review_status="approved"),               # not a paper -> skip
        _q(id="3", paper_type="pyq", review_status="pending_review"),        # not approved -> skip
        _q(id="4", paper_type="pyq", review_status="approved", correct_answer=None),  # ungradeable -> skip
    ]

    def _run(self, enabled):
        service = _Service({"id": "qs1", "subject_id": "subj1", "document_id": "doc1"})
        with patch.object(snap, "get_settings", return_value=SimpleNamespace(paper_bank_enabled=enabled)), \
             patch.object(snap, "select_all", return_value=[{"id": "v1"}]), \
             patch.object(snap, "select_all_in", side_effect=[[{"question_id": "1"}, {"question_id": "2"}, {"question_id": "3"}, {"question_id": "4"}], self.QUESTIONS]):
            added = snapshot_published_pyq(service, "t1", "qs1", "actor1")
        return added, service.rpc_calls

    def test_disabled_is_noop(self):
        added, calls = self._run(False)
        self.assertEqual(added, 0)
        self.assertEqual(calls, [])

    def test_only_approved_answerable_paper_snapshotted(self):
        added, calls = self._run(True)
        self.assertEqual(added, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sync_paper_questions")
        row = calls[0][1]["p_rows"][0]
        self.assertEqual(row["origin_question_id"], "1")
        self.assertEqual(row["paper_type"], "pyq")
        self.assertEqual(calls[0][1]["p_tenant_id"], "t1")
        self.assertEqual(row["chapter_id"], "ch1")
        self.assertEqual(row["year"], "2019")
        self.assertEqual(row["exam"], "CA")
        self.assertIn("content_hash", row)

    def test_rpc_failure_does_not_delete_bank_rows(self):
        service = _Service(
            {"id": "qs1", "subject_id": "subj1", "document_id": "doc1"},
            rpc_error=RuntimeError("database unavailable"),
        )
        with patch.object(snap, "get_settings", return_value=SimpleNamespace(paper_bank_enabled=True)), \
             patch.object(snap, "select_all", return_value=[]):
            self.assertEqual(snapshot_published_pyq(service, "t1", "qs1", "actor1"), 0)
        self.assertEqual(len(service.rpc_calls), 1)
        self.assertEqual(service.rpc_calls[0][1]["p_rows"], [])


class DescriptiveTests(unittest.TestCase):
    def test_flag_off_rejects_descriptive_even_with_model_answer(self):
        from app.services.quiz_extraction import _validate_import_candidates
        raw = {"questions": [{
            "type": "descriptive", "question_text": "Explain X.",
            "options": None, "correct_answer": None, "marks": 5,
            "model_answer": "A complete explanation.",
        }]}
        questions, summary = _validate_import_candidates(raw)
        self.assertEqual(questions, [])
        self.assertEqual(summary["skipped"], 1)

    def test_validation_accepts_descriptive_with_model_answer(self):
        from app.services.quiz_extraction import _validate_import_candidates
        raw = {"questions": [{
            "type": "descriptive", "question_text": "Explain the accrual concept.",
            "options": None, "correct_answer": None, "marks": 5,
            "model_answer": "Accrual means recognising income/expense when earned/incurred.",
            "answer_summary": "Recognise income when earned and expenses when incurred, not on cash.",
        }]}
        questions, summary = _validate_import_candidates(raw, paper_mode=True)
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
        questions, summary = _validate_import_candidates(raw, paper_mode=True)
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

    def test_ai_failure_requires_retry_instead_of_zero_marks(self):
        from app.services import descriptive_grader as dg
        items = [{"question_id": "q1", "answer_summary": "k", "student_answer": "ans"}]
        with patch.object(dg, "complete_json_with_fallback", side_effect=RuntimeError("down")):
            with self.assertRaises(dg.DescriptiveGradingUnavailable):
                dg.grade_descriptive(items)

    def test_incomplete_or_invalid_ai_grades_require_retry(self):
        from app.services import descriptive_grader as dg
        items = [{"question_id": "q1", "answer_summary": "k", "student_answer": "ans"}]
        for response in ({"grades": []}, {"grades": [{"id": "q1", "coverage": "NaN"}]},
                         {"grades": [{"id": "other", "coverage": 95}]}):
            with self.subTest(response=response), patch.object(
                dg, "complete_json_with_fallback", return_value=(response, "deepseek")
            ):
                with self.assertRaises(dg.DescriptiveGradingUnavailable):
                    dg.grade_descriptive(items)


class PaperSubmitSafetyTests(unittest.TestCase):
    ATTEMPT_ID = "00000000-0000-0000-0000-000000000001"
    PROFILE = CurrentProfile(user_id="student1", tenant_id="tenant1", role="student")
    DESCRIPTIVE = {
        "id": "q1", "subject_id": "subj1", "type": "descriptive",
        "question_text": "Explain X", "options": None, "correct_answer": None,
        "explanation": None, "marks": 5, "model_answer": "Model",
        "answer_summary": "Key points",
    }

    def _patches(self, row):
        class UpdateQuery:
            def update(self, _payload):
                return self

            def eq(self, *_args):
                return self

            def execute(self):
                return SimpleNamespace(data=[{"id": PaperSubmitSafetyTests.ATTEMPT_ID}])

        class Service:
            def table(self, name):
                assert name == "paper_attempts"
                return UpdateQuery()

        return (
            patch.object(papers, "get_settings", return_value=SimpleNamespace(
                paper_bank_enabled=True, rate_limit_paper_grading_per_hour=10,
            )),
            patch.object(papers, "get_service_client", return_value=Service()),
            patch.object(papers, "_load_attempt", return_value={
                "id": self.ATTEMPT_ID, "status": "in_progress", "question_snapshot": [row],
            }),
        )

    def test_descriptive_uses_separate_quota(self):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for setting in self._patches(self.DESCRIPTIVE):
                stack.enter_context(setting)
            limit = stack.enter_context(patch.object(papers, "enforce_ai_rate_limit"))
            stack.enter_context(patch.object(papers, "grade_descriptive", return_value={"q1": True}))
            result = papers.paper_submit(
                papers.SubmitRequest(attempt_id=self.ATTEMPT_ID, answers=[papers.SubmittedAnswer(
                    question_id="q1", student_answer="My explanation"
                )]), self.PROFILE,
            )
        self.assertEqual(result["score"], 5)
        self.assertEqual(papers.PaperScorecardOut.model_validate(result).status, "graded")
        self.assertEqual(limit.call_args.kwargs["endpoint"], "descriptive_grading")
        self.assertEqual(limit.call_args.kwargs["hourly_limit"], 10)

    def test_quota_or_provider_failure_does_not_return_zero_scorecard(self):
        from contextlib import ExitStack
        from app.services.descriptive_grader import DescriptiveGradingUnavailable

        body = papers.SubmitRequest(attempt_id=self.ATTEMPT_ID, answers=[papers.SubmittedAnswer(
            question_id="q1", student_answer="My explanation"
        )])
        with ExitStack() as stack:
            for setting in self._patches(self.DESCRIPTIVE):
                stack.enter_context(setting)
            stack.enter_context(patch.object(
                papers, "enforce_ai_rate_limit", side_effect=HTTPException(429, "Quota reached")
            ))
            grade = stack.enter_context(patch.object(papers, "grade_descriptive"))
            with self.assertRaises(HTTPException) as error:
                papers.paper_submit(body, self.PROFILE)
            self.assertEqual(error.exception.status_code, 429)
            grade.assert_not_called()

        with ExitStack() as stack:
            for setting in self._patches(self.DESCRIPTIVE):
                stack.enter_context(setting)
            stack.enter_context(patch.object(papers, "enforce_ai_rate_limit"))
            stack.enter_context(patch.object(
                papers, "grade_descriptive", side_effect=DescriptiveGradingUnavailable()
            ))
            with self.assertRaises(HTTPException) as error:
                papers.paper_submit(body, self.PROFILE)
            self.assertEqual(error.exception.status_code, 503)
            self.assertIn("not scored", error.exception.detail)

    def test_objective_answer_does_not_consume_ai_quota(self):
        from contextlib import ExitStack

        row = dict(self.DESCRIPTIVE, type="mcq_single", correct_answer="a")
        with ExitStack() as stack:
            for setting in self._patches(row):
                stack.enter_context(setting)
            limit = stack.enter_context(patch.object(papers, "enforce_ai_rate_limit"))
            result = papers.paper_submit(
                papers.SubmitRequest(attempt_id=self.ATTEMPT_ID, answers=[papers.SubmittedAnswer(
                    question_id="q1", student_answer="a"
                )]), self.PROFILE,
            )
        self.assertEqual(result["score"], 5)
        limit.assert_not_called()

    def test_blank_or_missing_answer_cannot_reveal_report(self):
        from contextlib import ExitStack

        row = dict(self.DESCRIPTIVE, type="mcq_single", correct_answer="a")
        with ExitStack() as stack:
            for setting in self._patches(row):
                stack.enter_context(setting)
            with self.assertRaises(HTTPException) as error:
                papers.paper_submit(
                    papers.SubmitRequest(
                        attempt_id=self.ATTEMPT_ID,
                        answers=[papers.SubmittedAnswer(question_id="q1", student_answer=None)],
                    ),
                    self.PROFILE,
                )
        self.assertEqual(error.exception.status_code, 400)
        self.assertFalse(papers._paper_answered("   "))


class PaperAttemptBoundaryTests(unittest.TestCase):
    ATTEMPT_ID = PaperSubmitSafetyTests.ATTEMPT_ID
    PROFILE = PaperSubmitSafetyTests.PROFILE

    class Query:
        def __init__(self, row=None):
            self.row = row
            self.filters = []
            self.inserted = None

        def select(self, *_args):
            return self

        def eq(self, column, value):
            self.filters.append((column, value))
            return self

        def maybe_single(self):
            return self

        def insert(self, payload):
            self.inserted = payload
            return self

        def execute(self):
            if self.inserted is not None:
                return SimpleNamespace(data=[{"id": PaperAttemptBoundaryTests.ATTEMPT_ID}])
            visible = self.row and all(self.row.get(column) == value for column, value in self.filters)
            return SimpleNamespace(data=self.row if visible else None)

    def test_start_snapshots_answers_but_only_returns_questions(self):
        row = dict(
            PaperSubmitSafetyTests.DESCRIPTIVE,
            paper_type="pyq", exam="CA", year="2025",
            options=[{"id": "a", "text": "Choice", "is_correct": True}],
        )
        query = self.Query()
        service = SimpleNamespace(table=lambda _name: query)
        with (
            patch.object(papers, "get_settings", return_value=SimpleNamespace(paper_bank_enabled=True)),
            patch.object(papers, "get_service_client", return_value=service),
            patch.object(papers, "_enrolled_or_404"),
            patch.object(papers, "_bank_rows", return_value=[row]),
        ):
            result = papers.paper_start(papers.StartRequest(paper_type="pyq", subject_id="subj1"), self.PROFILE)

        self.assertEqual(query.inserted["question_snapshot"][0]["answer_summary"], "Key points")
        self.assertNotIn("correct_answer", result["questions"][0])
        self.assertEqual(result["questions"][0]["options"], [{"id": "a", "text": "Choice"}])
        self.assertNotIn("answer_summary", papers.PaperTakingOut.model_validate(result).model_dump_json())

    def test_loading_attempt_requires_student_and_tenant(self):
        row = {
            "id": self.ATTEMPT_ID, "tenant_id": "tenant1", "student_id": "student1",
            "status": "in_progress", "paper_type": "pyq", "question_snapshot": [],
        }
        queries = []

        def table(_name):
            query = self.Query(row)
            queries.append(query)
            return query

        service = SimpleNamespace(table=table)
        papers._load_attempt(service, papers.UUID(self.ATTEMPT_ID), self.PROFILE)
        query = queries[0]
        self.assertIn(("tenant_id", "tenant1"), query.filters)
        self.assertIn(("student_id", "student1"), query.filters)
        with self.assertRaises(HTTPException) as error:
            papers._load_attempt(
                service, papers.UUID(self.ATTEMPT_ID),
                CurrentProfile(user_id="other-student", tenant_id="tenant1", role="student"),
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_ungraded_get_never_returns_snapshot_answer_keys(self):
        row = dict(PaperSubmitSafetyTests.DESCRIPTIVE, paper_type="pyq")
        attempt = {"id": self.ATTEMPT_ID, "status": "in_progress", "paper_type": "pyq", "question_snapshot": [row]}
        with (
            patch.object(papers, "get_settings", return_value=SimpleNamespace(paper_bank_enabled=True)),
            patch.object(papers, "get_service_client", return_value=object()),
            patch.object(papers, "_load_attempt", return_value=attempt),
        ):
            result = papers.paper_attempt(papers.UUID(self.ATTEMPT_ID), self.PROFILE)
        self.assertNotIn("model_answer", papers.PaperTakingOut.model_validate(result).model_dump_json())


class PaperSafetyMigrationTests(unittest.TestCase):
    def test_rpc_is_transactional_and_service_role_only(self):
        sql = (Path(__file__).resolve().parents[2]
               / "migrations/migration-65-paper-bank-safety.sql").read_text().lower()
        self.assertIn("create table if not exists public.paper_question_sources", sql)
        self.assertIn("create or replace function public.sync_paper_questions", sql)
        self.assertIn("security invoker", sql)
        self.assertIn("set search_path = ''", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)
        self.assertIn("descriptive_grading", sql)

    def test_paper_attempt_snapshots_are_private(self):
        sql = (Path(__file__).resolve().parents[2]
               / "migrations/migration-66-paper-attempts.sql").read_text().lower()
        self.assertIn("create table public.paper_attempts", sql)
        self.assertIn("alter table public.paper_attempts enable row level security", sql)
        self.assertIn("revoke all on public.paper_attempts from public, anon, authenticated", sql)
        self.assertIn("on delete cascade", sql)


if __name__ == "__main__":
    unittest.main()
