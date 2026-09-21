"""Offline regression fixtures for the first faculty pilot; no paid AI or DB."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.api.quiz import approve_all_questions
from app.lib.auth import CurrentProfile
from app.services.quiz_extraction import _merge_questions, _validate_import_candidates, extract_quiz
from app.services.review import get_quiz_set_detail
from app.services.selector import select_question_ids, select_question_ids_by_type


PROFILE = CurrentProfile(user_id="teacher-1", tenant_id="tenant-1", role="teacher")


class Query:
    def __init__(self, service, table):
        self.service, self.table = service, table
        self.filters = []
        self.payload = None
        self.inserting = False
        self.single = False
        self.columns = "*"

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, key, value):
        if key in {"options", "correct_answer", "verification_warnings"} and isinstance(value, str):
            value = json.loads(value)
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def is_(self, key, value):
        self.filters.append(lambda row: row.get(key) is None)
        return self

    def range(self, start, end):
        self.bounds = (start, end)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def maybe_single(self):
        self.single = True
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def insert(self, payload):
        self.payload, self.inserting = payload, True
        return self

    def execute(self):
        rows = self.service.tables.setdefault(self.table, [])
        if self.inserting:
            row = {"id": f"{self.table}-{len(rows) + 1}", **deepcopy(self.payload)}
            rows.append(row)
            return SimpleNamespace(data=[deepcopy(row)])
        matches = [row for row in rows if all(f(row) for f in self.filters)]
        if self.payload is not None:
            for row in matches:
                row.update(deepcopy(self.payload))
        result = deepcopy(matches)
        if hasattr(self, "bounds"):
            result = result[self.bounds[0]:self.bounds[1]+1]
        if self.columns != "*":
            result = [{key.strip(): row.get(key.strip()) for key in self.columns.split(",")} for row in result]
        return SimpleNamespace(data=(result[0] if result else None) if self.single else result)


class Service:
    def __init__(self, tables):
        self.tables = deepcopy(tables)

    def table(self, name):
        return Query(self, name)


def candidate(**changes):
    return {"type": "mcq_single", "question_text": "Which statement is correct?",
            "options": [{"id": "a", "text": "Alpha"}, {"id": "b", "text": "Beta"}],
            "correct_answer": "a", "confidence": 0.4, **changes}


def test_import_merge_preserves_repeated_stems_different_options_and_exact_occurrences():
    first = candidate()
    second = candidate(options=[{"id": "a", "text": "Gamma"}, {"id": "b", "text": "Delta"}])
    assert _merge_questions([{"questions": [first]}, {"questions": [second, first]}]) == [first, second, first]


def test_import_receipt_accounts_for_invalid_candidates_without_asserting_source_coverage():
    questions, receipt = _validate_import_candidates({"questions": [
        candidate(), candidate(correct_answer="missing"), None, candidate(question_text=" "),
    ]})
    assert len(questions) == 1
    assert (receipt["candidates"], receipt["imported"], receipt["skipped"]) == (4, 1, 3)
    assert [issue["candidate_index"] for issue in receipt["issues"]] == [2, 3, 4]
    assert all(issue["reason"] for issue in receipt["issues"])
    assert receipt["coverage_verified"] is False


def test_import_receipt_survives_reload_and_exposes_import_confidence():
    service = Service({
        "chapters": [{"id": "chapter-1", "subject_id": "subject-1", "tenant_id": "tenant-1", "name": "Basics"}],
        "documents": [{"id": "document-1", "tenant_id": "tenant-1", "uploaded_by": "teacher-1",
                       "storage_path": "private/paper.docx", "file_type": "docx"}],
    })
    raw = {"questions": [candidate(), candidate(correct_answer="invalid")]}
    with patch("app.services.quiz_extraction.get_service_client", return_value=service), \
         patch("app.services.quiz_extraction.teacher_has_subject", return_value=True), \
         patch("app.services.quiz_extraction.get_settings", return_value=SimpleNamespace(gemini_model="test")), \
         patch("app.services.quiz_extraction.download_bytes", return_value=b"fixture"), \
         patch("app.services.quiz_extraction._extract_document_content", return_value=(raw, "test")):
        result = extract_quiz(document_id="document-1", subject_id="subject-1", chapter_id="chapter-1", profile=PROFILE)
    with patch("app.services.review.get_service_client", return_value=service):
        reloaded = get_quiz_set_detail(result["quiz_set_id"], "tenant-1")
    assert result["extracted"] == 1 and result["skipped"] == 1
    assert reloaded["import_summaries"][0]["issues"] == result["import_summary"]["issues"]
    question = reloaded["variants"][0]["questions"][0]
    assert question["confidence_score"] == 0.4
    assert question["source"] == "extracted"
    assert question["review_status"] == "pending_review"
    with patch("app.services.review.get_service_client", return_value=service), pytest.raises(ValueError):
        get_quiz_set_detail(result["quiz_set_id"], "other-tenant")


def test_bulk_approval_includes_uncertain_but_preserves_rejected_and_other_owners():
    rows = [{**candidate(), "id": f"q-{index}", "verification_status": state,
             "review_status": "pending_review", "tenant_id": "tenant-1", "created_by": "teacher-1"}
            for index, state in enumerate(["verified", "unsupported", "ambiguous", "needs_teacher_review", None])]
    rows += [dict(rows[0], id="needs-edit", review_status="needs_edit"),
             dict(rows[0], id="malformed", correct_answer="not-an-option"),
             dict(rows[0], id="rejected", review_status="rejected"),
             dict(rows[0], id="other-owner", created_by="teacher-2"),
             dict(rows[0], id="other-tenant", tenant_id="tenant-2")]
    service = Service({
        "quiz_sets": [{"id": "quiz-1", "tenant_id": "tenant-1", "created_by": "teacher-1"}],
        "quiz_variants": [{"id": "variant-1", "quiz_set_id": "quiz-1", "tenant_id": "tenant-1"}],
        "quiz_variant_questions": [{"variant_id": "variant-1", "question_id": row["id"], "tenant_id": "tenant-1"} for row in rows],
        "questions": rows,
    })
    with patch("app.api.quiz.get_service_client", return_value=service), patch("app.api.quiz.log_events") as events:
        result = approve_all_questions("quiz-1", PROFILE)
    assert result == {"approved": 6, "skipped": 1}
    assert [row["id"] for row in service.tables["questions"] if row["review_status"] == "approved"] == [f"q-{i}" for i in range(5)] + ["needs-edit"]
    assert len(events.call_args.args[0]) == 6


@pytest.mark.parametrize("typed", [False, True])
def test_practice_excludes_draft_and_archived_questions_but_keeps_published_and_standalone_bank(typed):
    service = Service({
        "enrollments": [{"profile_id": "student-1", "tenant_id": "tenant-1", "course_id": "course-1"}],
        "subjects": [{"id": "subject-1", "course_id": "course-1", "tenant_id": "tenant-1"}],
        "chapters": [{"id": "chapter-1", "subject_id": "subject-1", "tenant_id": "tenant-1"}],
        "questions": [{"id": name, "chapter_id": "chapter-1", "tenant_id": "tenant-1",
                       "review_status": "approved", "type": "mcq_single"}
                      for name in ["draft", "archived", "published", "standalone"]],
        "quiz_variant_questions": [{"id": name, "question_id": name, "variant_id": name, "tenant_id": "tenant-1"}
                                   for name in ["draft", "archived", "published"]],
        "quiz_variants": [{"id": name, "quiz_set_id": name, "tenant_id": "tenant-1"}
                          for name in ["draft", "archived", "published"]],
        "quiz_sets": [{"id": name, "status": name, "tenant_id": "tenant-1"}
                      for name in ["draft", "archived", "published"]],
    })
    student = CurrentProfile(user_id="student-1", tenant_id="tenant-1", role="student")
    if typed:
        ids, available = select_question_ids_by_type(service, student, subject_id="subject-1", type_counts={"mcq_single": 10})
        assert available == {"mcq_single": 2}
    else:
        ids = select_question_ids(service, student, subject_id="subject-1", count=10)
    assert set(ids) == {"published", "standalone"}
