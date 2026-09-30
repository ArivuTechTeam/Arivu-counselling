from types import SimpleNamespace
from unittest.mock import Mock, patch

import fitz

from app.services.evaluation_references import normalize_question_ref, plausible_unbound_ref, ref_is_descendant
from app.services.evaluation_stage1 import (
    Stage1Outcome,
    merge_page_repairs,
    page_gaps,
    run_stage1,
    split_tables_by_row_ref,
)
from app.services.evaluation_stage1_contract import STAGE1_EXTRACTION_PROMPT
from app.services.evaluation_worker import _stage1_context
from tests.test_faculty_pilot_safety import Service


def extraction(*, manifest=None, answers=None, legibility="clear"):
    return {
        "text_answers": answers or [], "tables": [], "numerical_workings": [],
        "page_manifest": manifest or [],
        "legibility_report": {"overall_legibility": legibility,
            "difficult_questions": [], "illegible_questions": [], "language_detected": "English"},
    }


def answer(ref="1(a)", page=1):
    return {"question_ref": ref, "visible_question_ref": ref, "raw_text": "answer",
        "leading_continuation_ref": "", "leading_continuation_text": "",
        "selected_options": [], "selection_ambiguous": False, "word_count": 1,
        "has_headings": False, "has_diagrams": False, "has_tables": False,
        "source_document_index": 1, "source_pages": [page]}


def manifest(page=1, status="content"):
    return {"document_index": 1, "page_number": page, "status": status,
        "answer_content_present": status == "content", "question_refs": ["1(a)"] if status == "content" else [],
        "notes": ""}


def pdf_bytes(pages=1):
    document = fitz.open()
    for _ in range(pages):
        document.new_page().insert_text((72, 72), "Q1(a) answer")
    raw = document.tobytes(); document.close()
    return raw


def settings():
    return SimpleNamespace(gemini_stage1_model="gemini-stage1-test", gemini_stage1_max_output_tokens=32000,
                           gemini_stage1_thinking_budget=4000)


def submission(**extra):
    return {"tenant_id": "tenant-a", "answer_script_path": "tenant/student/answer.pdf",
            "stage1_extraction": {}, "stage1_extraction_source": None, "page_mapping": None, **extra}


def test_reference_normalization_exact_examples_and_boundaries():
    cases = {
        "1": "q1", "1(a)": "q1a", "1(a)(i)": "q1a1",
        "1A": "q1!a", "1B": "q1!b", "12B": "q12!b",
        "1.1": "q1_1", "1(i)": "q1_1", "11": "q11",
        "Q2(b)": "q2b", "Q1(a)(ii)": "q1a2", "Q1 (a) (ii)": "q1a2",
        "1(a)1": "q1a1", "Question-1.a": "q1a", "Question-1.a(1)": "q1a1",
        "Ans 4(b)": "q4b", "4(a)": "q4a", "2.": "q2", "2": "q2",
        # Phase B's approved contract intentionally omits the old underscore
        # after a fused alternative marker.
        "5A(i)": "q5!a1", "5(a)(i)": "q5a1", "1.2(i)": "q1_2_1",
    }
    for raw, expected in cases.items():
        assert normalize_question_ref(raw) == expected
    for rejected in ("4.1.23", "4.1.2026", "a", "", None):
        assert normalize_question_ref(rejected) == ""
    assert normalize_question_ref("1.1") != normalize_question_ref("11")
    assert not ref_is_descendant(normalize_question_ref("Q10"), normalize_question_ref("Q1"))
    assert not ref_is_descendant(normalize_question_ref("Q5A(i)"), normalize_question_ref("Q5"))
    assert plausible_unbound_ref("Debtors A/c") == ""


def test_stage1_prompt_contains_examapp_edge_case_instructions():
    for phrase in (
        "SELECTED-RESPONSE TRANSCRIPTION IS NOT GRADING",
        "CARET-INSERTED CORRECTIONS",
        "STUDENTS ANSWER OUT OF ORDER",
        "SHORTHAND PARENT BOUNDARIES ARE STILL BOUNDARIES",
        "QUESTION-BOUNDARY SWEEP (MANDATORY)",
        "JOURNAL ENTRIES ARE ALWAYS TABLES",
        "PAGE-BY-PAGE COMPLETENESS SWEEP (MANDATORY)",
    ):
        assert phrase in STAGE1_EXTRACTION_PROMPT


def test_clean_extraction_and_gemini_stage1_config():
    response = extraction(manifest=[manifest()], answers=[answer()])
    call = Mock(return_value=response)
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, job_id="job-a", gemini_call=call)
    assert outcome.requires_review is False
    assert outcome.extraction["text_answers"][0]["raw_text"] == "answer"
    assert outcome.page_mapping == {"1(a)": [{"document_index": 1, "page_number": 1}]}
    assert call.call_args.kwargs["model"] == "gemini-stage1-test"
    assert call.call_args.kwargs["temperature"] == 0.0
    assert call.call_args.kwargs["max_output_tokens"] == 32000
    assert call.call_args.kwargs["thinking_budget"] == 4000


def test_stage1_reads_primary_and_verified_additional_pages_as_two_documents():
    response = extraction(manifest=[
        {**manifest(1, "blank"), "document_index": 1},
        {**manifest(1, "blank"), "document_index": 2},
    ])
    call = Mock(return_value=response)
    current = submission(additional_pages_path="tenant/student/additional.pdf")
    with patch("app.services.evaluation_stage1.download_bytes",
               side_effect=[pdf_bytes(), pdf_bytes()]), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), current, {}, job_id="job-a", gemini_call=call)
    files = call.call_args.args[2]
    assert len(files) == 2
    assert outcome.source == (
        '["tenant/student/answer.pdf","tenant/student/additional.pdf"]'
    )


def test_impossible_provenance_is_rejected_then_retried_cleanly():
    invented = extraction(manifest=[manifest(2)], answers=[answer(page=2)])
    good = extraction(manifest=[manifest()], answers=[answer()])
    call = Mock(side_effect=[invented, good])
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert call.call_count == 2
    assert outcome.requires_review is False


def test_whole_script_illegible_routes_to_review_without_repair():
    call = Mock(return_value=extraction(manifest=[manifest(status="unreadable")], legibility="illegible"))
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert outcome.requires_review is True
    assert call.call_count == 1


def test_missing_page_gets_one_focused_repair_and_authoritative_merge():
    primary = extraction()
    repaired = extraction(manifest=[manifest()], answers=[answer()])
    call = Mock(side_effect=[primary, repaired])
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert call.call_count == 2
    assert outcome.requires_review is False
    assert outcome.extraction["targeted_page_repairs"] == [{"document_index": 1, "page_number": 1}]


def test_more_than_six_missing_pages_skips_repair_and_flags_review():
    call = Mock(return_value=extraction())
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes(7)), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert call.call_count == 1
    assert outcome.requires_review is True
    assert len(outcome.extraction["page_verification"]["unverified_pages"]) == 7


def test_page_question_mapping_disagreement_is_audit_only_like_examapp():
    page = manifest()
    page["question_refs"] = ["1(a)"]
    call = Mock(return_value=extraction(
        manifest=[page],
        answers=[answer("1(b)")],
    ))
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert outcome.requires_review is False
    assert "page_verification" not in outcome.extraction
    assert call.call_count == 1


def test_repair_inventing_provenance_is_discarded_and_flagged():
    call = Mock(side_effect=[extraction(), extraction(manifest=[manifest(2)], answers=[answer(page=2)])])
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        outcome = run_stage1(Mock(), submission(), {}, gemini_call=call)
    assert outcome.requires_review is True
    assert outcome.extraction["text_answers"] == []
    assert outcome.extraction["page_verification"]["repair_attempted"] is True


def test_cache_reuse_and_explicit_re_evaluation():
    cached = extraction(manifest=[manifest()], answers=[answer()])
    call = Mock(return_value=cached)
    current = submission(stage1_extraction=cached,
                         stage1_extraction_source="tenant/student/answer.pdf")
    outcome = run_stage1(Mock(), current, {}, gemini_call=call)
    assert isinstance(outcome, Stage1Outcome)
    call.assert_not_called()
    with patch("app.services.evaluation_stage1.download_bytes", return_value=pdf_bytes()), \
         patch("app.services.evaluation_stage1.get_settings", return_value=settings()):
        run_stage1(Mock(), current, {}, explicit_re_evaluation=True, gemini_call=call)
    call.assert_called_once()


def test_table_split_inherits_blank_narration_and_recomputes_dr_cr():
    table = {"question_ref": "1(a)", "visible_question_ref": "1(a)",
        "headers": ["Particulars", "Dr", "Cr"],
        "rows": [["Cash", "100", ""], ["(Being entry)", "", ""], ["Sales", "", "100"]],
        "row_question_refs": ["1(a)", "", "1(b)"], "row_visible_question_refs": ["1(a)", "", "1(b)"],
        "difficult_cells": [], "source_document_index": 1, "source_pages": [1]}
    result = split_tables_by_row_ref({"tables": [table]}, ["1(a)", "1(b)"])
    assert len(result["tables"]) == 2
    assert result["tables"][0]["rows"][1][0] == "(Being entry)"
    assert result["tables"][0]["computed_dr_total"] == 100
    assert result["tables"][1]["computed_cr_total"] == 100


def test_merge_retains_fragment_spanning_good_and_repaired_pages():
    spanning = answer(); spanning["source_pages"] = [1, 2]
    primary = extraction(manifest=[manifest(1), manifest(2)], answers=[spanning, answer(page=2)])
    repair = extraction(manifest=[manifest(2)], answers=[answer("1(b)", 2)])
    merged = merge_page_repairs(primary, repair, {(1, 2)})
    assert spanning in merged["text_answers"]
    assert all(item != answer(page=2) for item in merged["text_answers"])


def test_page_gap_status_names_are_stable():
    data = extraction(manifest=[{**manifest(), "status": "mystery"}])
    assert page_gaps(data, [{"document_index": 1, "page_count": 1}])[0]["reason"] == "invalid_status"


def test_worker_stage1_context_never_loads_cross_tenant_paper_payload():
    service = Service({
        "handwritten_submissions": [{"id": "submission-a", "tenant_id": "tenant-a",
            "student_id": "student-a", "evaluation_paper_id": "paper-a",
            "answer_script_path": "a.pdf", "stage1_extraction": {},
            "stage1_extraction_source": None, "page_mapping": None}],
        "evaluation_papers": [{"id": "paper-a", "tenant_id": "tenant-a",
            "generated_paper_id": "generated-a", "is_active": True}],
        "generated_papers": [
            {"id": "generated-a", "tenant_id": "tenant-a", "paper_payload": {"sections": []}},
            {"id": "generated-a", "tenant_id": "tenant-b",
             "paper_payload": {"sections": [{"questions": [{"number": "SECRET"}]}]}},
        ],
    })
    submission_row, paper = _stage1_context(service, {"submission_id": "submission-a",
        "tenant_id": "tenant-a", "owner_student_id": "student-a"})
    assert submission_row["tenant_id"] == "tenant-a"
    assert paper["paper_payload"] == {"sections": []}
