"""Synthetic commerce fixtures; no provider calls or institutional documents."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.blueprint import BPQuestion, _generate_with_exact_mix
from app.services.extraction import ExtractedText, PageSpan, require_readable_generation_pages
from app.services.import_fidelity import inventory, question_chunks, reconcile
from app.services.quiz_extraction import _extract_document_content, _text_extract, _validate_import_candidates
from app.services.question_grounding import GroundingCheck
from app.services.question_repair import repair_candidates
from app.services.question_verification import _source_context, verify_generated_questions

PAPER = """1. Which balance is an asset?
a) Cash
b) Loan payable

2. Which balance is a liability?
a) Inventory
b) Loan payable

Answer key
1. A  2. B
"""


def candidate(stem="Which balance is an asset?", **changes):
    return {"question_text": stem, "type": "mcq_single",
            "options": [{"id": "a", "text": "Cash"}, {"id": "b", "text": "Loan payable"}],
            "correct_answer": "b", "confidence": 0.6, **changes}


def test_independent_inventory_detects_missing_item_and_retains_source_key():
    raw = reconcile({"questions": [candidate()]}, inventory(PAPER))
    questions, receipt = _validate_import_candidates(raw)
    assert questions[0].correct_answer == "a"
    assert questions[0].verification_status == "needs_teacher_review"
    assert any("differed" in w for w in questions[0].verification_warnings)
    source = receipt["source_inventory"]
    assert source["detected"] == 2 and source["matched"] == 1
    assert source["missing"][0]["source_number"] == "2"
    assert source["items"][0]["answer_origin"] == "source_key"
    assert source["items"][0]["state"] == "imported"
    assert receipt["coverage_verified"] is False


def test_repeated_numbers_and_conflicting_keys_never_silently_choose_answer():
    repeated = PAPER.replace("2. Which", "1. Which")
    raw = reconcile({"questions": [candidate()]}, inventory(repeated))
    assert raw["questions"][0]["correct_answer"] == "b"
    assert raw["source_inventory"]["warnings"]
    conflicting = PAPER.replace("1. A  2. B", "1. A  1. B  2. B")
    raw = reconcile({"questions": [candidate()]}, inventory(conflicting))
    assert raw["source_inventory"]["items"][0]["answer_origin"] == "conflicting_source_keys"
    assert raw["questions"][0]["correct_answer"] == "b"


def test_key_does_not_attach_to_changed_options_or_unmatched_stem():
    changed = candidate(options=[{"id": "a", "text": "Loan payable"}, {"id": "b", "text": "Cash"}])
    raw = reconcile({"questions": [changed, candidate("A rewritten question?")]}, inventory(PAPER))
    assert raw["questions"][0]["correct_answer"] == "b"
    assert raw["source_inventory"]["items"][0]["answer_origin"] == "inferred_or_unconfirmed"
    assert "source_excerpt" not in raw["questions"][1]


def test_invalid_candidate_is_counted_as_unresolved_source_item():
    raw = reconcile({"questions": [candidate(type="unsupported")]}, inventory(PAPER))
    questions, receipt = _validate_import_candidates(raw)
    assert questions == [] and receipt["skipped"] == 1
    assert receipt["source_inventory"]["items"][0]["state"] == "unresolved"


def test_question_chunks_keep_options_and_oversize_fails_explicitly():
    chunks = question_chunks(PAPER, 100)
    assert any("1. Which balance is an asset?\na) Cash\nb) Loan payable" in chunk for chunk in chunks)
    with pytest.raises(ValueError, match="complete sections"):
        question_chunks("1. " + "Long question " * 100 + "\na) A\nb) B", 100)


def test_key_join_works_across_chunks_without_extra_model_call():
    def extract(_system, user):
        if "1. Which balance" in user:
            return {"questions": [candidate()]}, "fixture"
        if "2. Which balance" in user:
            return {"questions": [candidate("Which balance is a liability?",
                options=[{"id": "a", "text": "Inventory"}, {"id": "b", "text": "Loan payable"}], correct_answer="a")]}, "fixture"
        return {"questions": []}, "fixture"
    with patch("app.services.quiz_extraction.get_settings", return_value=SimpleNamespace(
        extraction_text_chunk_chars=100, extraction_chunk_concurrency=2)), patch(
        "app.services.quiz_extraction.complete_json_with_fallback", side_effect=extract) as model:
        raw, _ = _text_extract(PAPER)
    assert [q["correct_answer"] for q in raw["questions"]] == ["a", "b"]
    assert model.call_count == len(question_chunks(PAPER, 100))


def test_mixed_pdf_includes_scan_in_visual_processing():
    text = PAPER * 4
    extracted = ExtractedText(text, (PageSpan(1, 0, len(text)), PageSpan(2, len(text), len(text))))
    with patch("app.services.quiz_extraction.extract_text_with_pages", return_value=extracted), patch(
        "app.services.quiz_extraction._vision_extract", return_value=({"questions": []}, "vision")) as vision, patch(
        "app.services.quiz_extraction._text_extract") as text_model:
        raw, _ = _extract_document_content(content=b"fixture", ext="pdf")
    vision.assert_called_once_with("application/pdf", b"fixture")
    text_model.assert_not_called()
    assert raw["source_manifest"]["sparse_pages"] == [2]


def test_typed_pdf_source_page_is_attached_to_matched_question():
    with patch("app.services.quiz_extraction.get_settings", return_value=SimpleNamespace(
        extraction_text_chunk_chars=18000)), patch("app.services.quiz_extraction.complete_json_with_fallback",
        return_value=({"questions": [candidate()]}, "fixture")):
        raw, _ = _text_extract(PAPER, (PageSpan(4, 0, len(PAPER)),))
    assert raw["questions"][0]["source_page_start"] == 4


def test_context_uses_original_evidence_and_duplicate_verifier_indices_fail_safe():
    excerpt = "Cash is classified as a current asset."
    material = excerpt + " Loan payable is a liability owed to the lender."
    assert "liability" in _source_context(excerpt, material)
    q = BPQuestion(**candidate(correct_answer="a", explanation="Cash represents resources owned by the business.",
                                source_excerpt=excerpt, grounding_confidence=0.9))
    response = {"questions": [{"index": 0, "status": "unsupported"}, {"index": 0, "status": "verified"}]}
    with patch("app.services.question_verification.complete_json_with_fallback", return_value=(response, "fixture")):
        checks = verify_generated_questions([q], material)
    assert checks[0].status == "needs_teacher_review"
    assert any("unavailable" in warning for warning in checks[0].warnings)


def test_selective_repair_preserves_good_questions_and_requires_reverification():
    questions = [BPQuestion(**candidate(topic="Assets", marks=2)), BPQuestion(**candidate("Which balance is a liability?", topic="Liabilities"))]
    checks = [GroundingCheck(), GroundingCheck("unsupported", ["Evidence mismatch"])]
    replacement = questions[1].model_copy(update={"explanation": "Loan payable represents an obligation to repay the lender."})
    complete = Mock(return_value=({"repairs": [{"index": 1, "question": replacement.model_dump()}]}, "fixture"))
    verify = Mock(return_value=[GroundingCheck(), GroundingCheck()])
    updated, _, report = repair_candidates(questions, checks, PAPER, "medium", complete=complete, verify=verify)
    assert updated[0] is questions[0]
    assert updated[1].explanation == replacement.explanation
    assert report["accepted"] == 1
    verify.assert_called_once()
    # A replacement that damages an unchanged candidate is never committed.
    verify.return_value = [GroundingCheck("unsupported"), GroundingCheck()]
    updated, _, report = repair_candidates(questions, checks, PAPER, "medium", complete=complete, verify=verify)
    assert updated is questions and report["accepted"] == 0


def test_repair_rejects_changed_allocation_and_does_not_retry_verifier_outages():
    q = BPQuestion(**candidate(topic="Assets", marks=2))
    altered = q.model_copy(update={"type": "mcq_multi", "correct_answer": ["a"]})
    complete = Mock(return_value=({"repairs": [{"index": 0, "question": altered.model_dump()}]}, "fixture"))
    verify = Mock()
    updated, _, report = repair_candidates([q], [GroundingCheck("unsupported")], PAPER, "medium", complete=complete, verify=verify)
    assert updated[0] is q and report["accepted"] == 0
    verify.assert_not_called()
    complete.reset_mock()
    repair_candidates([q], [GroundingCheck("needs_teacher_review")], PAPER, "medium", complete=complete, verify=verify)
    complete.assert_not_called()


def test_source_shortfall_does_not_trigger_full_generation_retry():
    with patch("app.services.blueprint.complete_json_with_fallback", return_value=(
        {"source_insufficient": True, "questions": []}, "fixture")) as model:
        with pytest.raises(ValueError, match="Reduce the question count"):
            _generate_with_exact_mix("system", "user", {"mcq_single": 10})
    model.assert_called_once()


def test_generation_rejects_scanned_page_but_allows_blank_separator():
    extracted = ExtractedText(PAPER, (PageSpan(1, 0, len(PAPER)), PageSpan(2, len(PAPER), len(PAPER), True)))
    with pytest.raises(ValueError, match="Pages 2"):
        require_readable_generation_pages(extracted)
    require_readable_generation_pages(ExtractedText(PAPER, (PageSpan(2, len(PAPER), len(PAPER)),)))


def test_interleaved_section_keys_do_not_join_across_sections():
    paper = PAPER.replace("\n2. Which", "\nAnswer key\n1. A\n\n2. Which")
    source = inventory(paper)
    assert len(source["items"]) == 2
    assert source["warnings"]
    assert not any(item["keys"] for item in source["items"])
