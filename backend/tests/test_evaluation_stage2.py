from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.evaluation_stage2 import (
    CompiledStage2, Stage2ContractError, Stage2PermanentError, Stage2RetryableError,
    answer_presence, apply_choices,
    build_evidence_groups, compile_question, compile_response, direct_score_mark, fixed_payload,
    deterministic_mcq, map_evidence_to_rubric, validate_fixed_rubric,
)
from app.services.evaluation_stage2_runner import run_stage2
from app.services.evaluation_stage2_transport import deepseek_stage2
from app.services.evaluation_worker import run_one


def criterion(cid="c1", marks=1):
    return {"criterion_id": cid, "criterion": "Correct treatment", "marks": marks}


def question(ref="Q1", marks=1, **extra):
    return {"question_ref": ref, "question_text": ref, "suggested_answer": "Answer",
            "marks": marks, "evaluation_criteria": [criterion(marks=marks)], **extra}


def test_fixed_rubric_rejects_every_pre_send_invariant():
    assert validate_fixed_rubric([question()])[0]["total_marks"] == 1
    derived = question(marks=0); derived["evaluation_criteria"] = [criterion(marks=.5)]
    assert validate_fixed_rubric([derived])[0]["total_marks"] == .5
    invalid = [
        [], [{**question(), "question_ref": ""}], [question(), question("q1")],
        [{**question(), "evaluation_criteria": []}],
        [{**question(), "marks": 2}],
        [{**question(), "evaluation_criteria": [criterion("x"), criterion("x")]}],
        [{**question(), "marks": float("nan")}],
        [{**question(), "evaluation_criteria": [criterion(marks=-1)]}],
    ]
    for rows in invalid:
        with pytest.raises(Stage2PermanentError):
            validate_fixed_rubric(rows)


def test_evidence_chunks_ids_presence_and_caption_inheritance_are_stable():
    extraction = {"text_answers": [
        {"question_ref": "Q2", "raw_text": "First sentence. Second sentence.\n- Third", "source_document_index": 1, "source_pages": [2]},
        {"question_ref": "", "raw_text": "Caption continuation", "source_document_index": 1, "source_pages": [2]},
        {"question_ref": "Q3", "raw_text": "ILLEGIBLE", "source_pages": [3]},
    ]}
    first, unsafe = build_evidence_groups(extraction)
    second, _ = build_evidence_groups(extraction)
    assert first == second
    q2 = next(row for row in first if row["ref_group"] == "Q2")
    assert len(q2["evidence"]) == 4
    assert all(len(row["evidence_id"]) == 8 for row in q2["evidence"])
    assert unsafe
    assert answer_presence({"evidence": q2["evidence"], "attempt_signal": False}) == "substantive"
    assert answer_presence({"evidence": [], "attempt_signal": True}) == "attempted_ungradable"
    assert answer_presence({"evidence": [], "attempt_signal": False}) == "none"


def test_mapping_copies_coarse_refs_to_descendants_and_routes_unmatched():
    rubric = validate_fixed_rubric([question("Q2(b)(i)"), question("Q2(b)(ii)")])
    mapped, unmatched = map_evidence_to_rubric(rubric, {"text_answers": [
        {"question_ref": "Q2(b)", "raw_text": "Shared work"},
        {"question_ref": "Q9", "raw_text": "Unknown work"},
    ]})
    assert all(mapped[key]["evidence"] for key in mapped)
    assert unmatched[0]["ref_group"] == "Q9"


@pytest.mark.parametrize(("raw", "expected"), [(.24, 0), (.25, .5), (.74, .5), (.75, 1), (1.26, 1.5)])
def test_half_mark_quantization(raw, expected):
    assert direct_score_mark(raw, 2) == expected


def test_off_grid_max_allows_only_zero_or_exact_max():
    assert direct_score_mark(.75, .75) == .75
    assert direct_score_mark(.5, .75) == 0
    assert direct_score_mark(.1, .25) == 0


def _payload_question(presence, evidence=None):
    return {"question_ref": "Q1", "question_text": "Q", "total_marks": 1,
            "evaluation_criteria": [criterion()], "answer_presence": presence,
            "student_evidence": evidence or [], "extraction_uncertain": False}


def test_mapping_states_are_forced_and_dependent_unknown_id_is_terminal():
    safe = _payload_question("substantive", [{"evidence_id": "own", "text": "answer"}])
    parsed = {"mapping_status": "blank", "recovered_evidence_ids": ["invented"],
              "criteria_breakdown": [{"criterion_id": "c1", "marks_awarded": 1}]}
    assert compile_question(safe, parsed, [])["mapping_status"] == "matched"
    unsafe = compile_question(_payload_question("attempted_ungradable"), parsed, [])
    assert unsafe["not_evaluated"] and unsafe["mapping_status"] == "unsafe"
    blank = compile_question(_payload_question("none"), {"mapping_status": "matched", "criteria_breakdown": []}, [])
    assert blank["not_attempted"] and blank["mapping_status"] == "blank"
    with pytest.raises(Stage2ContractError):
        compile_question(_payload_question("none"), parsed, [])


def test_whole_paper_keeps_valid_sibling_when_one_question_cites_unknown_evidence():
    first = _payload_question("substantive", [{"evidence_id": "own", "text": "answer"}])
    second = {**_payload_question("none"), "question_ref": "Q2", "question_text": "Q2"}
    raw = '{"results":[' \
        '{"question_ref":"Q1","mapping_status":"matched","criteria_breakdown":' \
        '[{"criterion_id":"c1","marks_awarded":1}]},' \
        '{"question_ref":"Q2","mapping_status":"recovered",' \
        '"recovered_evidence_ids":["invented"],"criteria_breakdown":' \
        '[{"criterion_id":"c1","marks_awarded":1}]}]}'

    results, requires_review = compile_response(
        {"questions": [first, second], "other_unmatched_evidence": []}, raw,
    )

    assert results[0]["marks_obtained"] == 1
    assert results[0]["not_evaluated"] is False
    assert results[1]["marks_obtained"] == 0
    assert results[1]["not_evaluated"] is True
    assert requires_review is True


def test_whole_paper_still_rejects_duplicate_unmatched_evidence_ownership():
    questions = [
        _payload_question("none"),
        {**_payload_question("none"), "question_ref": "Q2", "question_text": "Q2"},
    ]
    unmatched = [{"evidence_id": "shared", "text": "answer"}]
    raw = '{"results":[' \
        '{"question_ref":"Q1","mapping_status":"recovered",' \
        '"recovered_evidence_ids":["shared"],"criteria_breakdown":' \
        '[{"criterion_id":"c1","marks_awarded":1}]},' \
        '{"question_ref":"Q2","mapping_status":"recovered",' \
        '"recovered_evidence_ids":["shared"],"criteria_breakdown":' \
        '[{"criterion_id":"c1","marks_awarded":1}]}]}'

    with pytest.raises(Stage2ContractError, match="same unmatched evidence"):
        compile_response({"questions": questions, "other_unmatched_evidence": unmatched}, raw)


def test_choice_rules_best_alternative_tie_and_printed_order_slots():
    def result(ref, score, blank=False):
        return {"question_ref": ref, "marks_obtained": score, "not_attempted": blank,
                "not_counted": False}
    alternatives = apply_choices([result("Q5A", 2), result("Q5B", 3)], None)
    assert [row["not_counted"] for row in alternatives] == [True, False]
    tie = apply_choices([result("Q5A", 3), result("Q5B", 3)], None)
    assert [row["not_counted"] for row in tie] == [False, True]
    subparts = apply_choices([
        result("Q5A(i)", 2), result("Q5A(ii)", 2),
        result("Q5B(i)", 3), result("Q5B(ii)", 0),
    ], None)
    assert [row["not_counted"] for row in subparts] == [False, False, True, True]
    picked = apply_choices([result("Q1", 1), result("Q2", 5), result("Q3", 9)],
                           {"optional_groups": [{"pick": 2, "questions": ["Q1", "Q2", "Q3"]}]})
    assert [row["not_counted"] for row in picked] == [False, False, True]
    blank_slot = apply_choices([result("Q1", 0, True), result("Q2", 0, True), result("Q3", 9)],
                               {"optional_groups": [{"pick": 2, "questions": ["Q1", "Q2", "Q3"]}]})
    assert [row["not_counted"] for row in blank_slot] == [False, True, False]


@pytest.mark.parametrize(("selection", "presence", "marks", "blank", "review"), [
    ("A", "substantive", 1, False, False),
    ("B", "substantive", 0, False, False),
    (None, "none", 0, True, False),
    (None, "attempted_ungradable", 0, False, True),
])
def test_deterministic_mcq_correct_wrong_blank_and_ambiguous(selection, presence, marks, blank, review):
    evidence = [] if selection is None else [{"type": "mcq_selection", "text": f"Selected option: {selection}"}]
    row = _payload_question(presence, evidence)
    row.update(question_type="mcq_single", options=[{"label": "A"}, {"label": "B"}], correct_option="A")
    result = deterministic_mcq(row)
    assert result["marks_obtained"] == marks
    assert result["not_attempted"] is blank
    assert result["not_evaluated"] is review


class SlotService:
    def rpc(self, name, params):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=True))


class Response:
    def __init__(self, status, data=None): self.status_code, self.data = status, data
    def json(self):
        if isinstance(self.data, Exception): raise self.data
        return self.data


def transport_settings():
    return SimpleNamespace(deepseek_api_key="key", deepseek_model="model",
                           deepseek_base_url="https://deepseek.example",
                           deepseek_slot_wait_seconds=1, deepseek_max_concurrency=24,
                           deepseek_stage2_max_tokens=80000,
                           deepseek_stage2_thinking_effort="high")


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_deepseek_permanent_http_never_retries(status):
    post = Mock(return_value=Response(status))
    with patch("app.services.evaluation_stage2_transport.log_ai_call"), pytest.raises(Stage2PermanentError):
        deepseek_stage2(SlotService(), "system", "{}", post=post, sleep=Mock(), settings=transport_settings())
    assert post.call_count == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_deepseek_retryable_http_uses_five_and_ten_second_backoff(status):
    success = Response(200, {"model": "m", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    post, sleep = Mock(side_effect=[Response(status), Response(status), success]), Mock()
    with patch("app.services.evaluation_stage2_transport.log_ai_call"):
        assert deepseek_stage2(SlotService(), "system", "{}", post=post, sleep=sleep, settings=transport_settings()).content == "{}"
    assert [call.args[0] for call in sleep.call_args_list] == [5, 10]


def test_received_malformed_response_is_not_regenerated():
    post = Mock(return_value=Response(200, ValueError("bad json")))
    with patch("app.services.evaluation_stage2_transport.log_ai_call"), pytest.raises(Stage2PermanentError):
        deepseek_stage2(SlotService(), "system", "{}", post=post, sleep=Mock(), settings=transport_settings())
    assert post.call_count == 1


def test_stage2_transport_uses_text_mode_and_exact_scoring_limits():
    response = Response(200, {"model": "m", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    post = Mock(return_value=response)
    with patch("app.services.evaluation_stage2_transport.log_ai_call"):
        deepseek_stage2(SlotService(), "system", "{}", post=post, sleep=Mock(), settings=transport_settings())
    request = post.call_args.kwargs
    assert request["json"]["response_format"] == {"type": "text"}
    assert request["json"]["max_tokens"] == 80000
    assert request["json"]["temperature"] == 0
    assert request["json"]["reasoning_effort"] == "high"
    assert request["timeout"] == 180.0


def test_stage2_transport_uses_per_question_override_and_logs_truncation_as_error():
    response = Response(200, {
        "model": "deepseek-v4-flash",
        "usage": {"prompt_tokens": 100, "completion_tokens": 32000},
        "choices": [{"finish_reason": "length", "message": {"content": "partial"}}],
    })
    post, logger = Mock(return_value=response), Mock()
    with patch("app.services.evaluation_stage2_transport.log_ai_call", logger), \
         pytest.raises(Stage2PermanentError, match="truncated"):
        deepseek_stage2(
            SlotService(), "system", "{}", post=post, sleep=Mock(),
            settings=transport_settings(), max_tokens=32000,
        )
    assert post.call_args.kwargs["json"]["max_tokens"] == 32000
    assert logger.call_args.kwargs["error_message"] == "output truncated at token limit"


def test_all_deterministic_mcqs_skip_deepseek_entirely():
    rubric = [question("Q1", question_type="mcq_single",
                       options=[{"label": "A"}, {"label": "B"}], correct_option="A")]
    submission = {"id": "s", "tenant_id": "t", "student_id": "u", "stage1_extraction": {
        "text_answers": [{"question_ref": "Q1", "selected_options": ["A"]}]
    }}
    paper = {"tenant_id": "t", "subject_id": "sub", "structured_qa": rubric,
             "rubric_source": "official", "question_structure": {}}
    settings = SimpleNamespace(per_question_stage2_enabled=False, per_question_stage2_concurrency=5,
                               rate_limit_handwritten_evaluation_per_hour=10)
    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=settings), \
         patch("app.services.evaluation_stage2_runner.deepseek_stage2") as call:
        outcome = run_stage2(Mock(), submission, paper)
    call.assert_not_called()
    assert outcome.total_obtained == 1


def test_worker_resumes_stage1_checkpoint_and_atomically_finishes_stage2():
    job = {"id": "j", "tenant_id": "t", "submission_id": "s",
           "owner_student_id": "u", "attempts": 1, "kind": "evaluate_submission"}
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    submission = {"id": "s", "tenant_id": "t", "student_id": "u",
                  "stage1_extraction": {"text_answers": []}}
    paper = {"id": "p", "tenant_id": "t", "rubric_status": "ready"}
    scored = CompiledStage2(
        questions=[{"question_ref": "Q1", "marks_obtained": 1, "marks_possible": 2,
                    "not_counted": False, "not_evaluated": False,
                    "handwriting_legibility": "clear"}],
        artifacts=[], total_obtained=1, total_possible=2, requires_review=False,
    )
    with patch("app.services.evaluation_worker._authorized_submission", return_value=True), \
         patch("app.services.evaluation_worker._stage1_context", return_value=(submission, paper)), \
         patch("app.services.evaluation_worker.run_stage1") as stage1, \
         patch("app.services.evaluation_worker.run_stage2", return_value=scored) as stage2, \
         patch("app.services.evaluation_worker._run_learning_follow_on") as learning:
        assert run_one(service, worker_id="worker") is True
    stage1.assert_not_called()
    stage2.assert_called_once_with(
        service, submission, paper, job_id="j", force_review=False,
    )
    assert [call.args[0] for call in service.rpc.call_args_list] == [
        "claim_evaluation_job", "start_evaluation_job", "begin_evaluation_stage2",
        "finish_evaluation_stage2_job",
    ]
    finish = service.rpc.call_args_list[-1].args[1]
    assert finish["p_summary"]["total_marks_obtained"] == 1
    assert finish["p_summary"]["percentage"] == 50
    learning.assert_called_once()


def test_cached_stage1_review_signal_completes_stage2_and_flags_report():
    job = {"id": "j", "tenant_id": "t", "submission_id": "s",
           "owner_student_id": "u", "attempts": 1, "kind": "evaluate_submission"}
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    submission = {
        "id": "s", "tenant_id": "t", "student_id": "u",
        "stage1_extraction": {
            "text_answers": [],
            "page_verification": {"requires_review": True},
            "legibility_report": {"overall_legibility": "clear"},
        },
    }
    paper = {"id": "p", "tenant_id": "t", "rubric_status": "ready"}
    scored = CompiledStage2(
        questions=[{"question_ref": "Q1", "marks_obtained": 0, "marks_possible": 2,
                    "not_counted": False, "not_evaluated": True,
                    "handwriting_legibility": "difficult"}],
        artifacts=[], total_obtained=0, total_possible=2, requires_review=True,
    )
    with patch("app.services.evaluation_worker._authorized_submission", return_value=True), \
         patch("app.services.evaluation_worker._stage1_context", return_value=(submission, paper)), \
         patch("app.services.evaluation_worker.run_stage2", return_value=scored) as stage2, \
         patch("app.services.evaluation_worker._run_learning_follow_on") as learning:
        assert run_one(service, worker_id="worker") is True
    stage2.assert_called_once_with(
        service, submission, paper, job_id="j", force_review=True,
    )
    finish = service.rpc.call_args_list[-1].args[1]
    assert finish["p_review"] is True
    learning.assert_not_called()


def test_stage1_page_uncertainty_remains_scoreable_but_forces_review():
    rubric = [question("Q1", question_type="mcq_single",
                       options=[{"label": "A"}, {"label": "B"}], correct_option="A")]
    submission = {"id": "s", "tenant_id": "t", "student_id": "u", "stage1_extraction": {
        "text_answers": [{"question_ref": "Q1", "selected_options": ["A"],
                          "page_verification_uncertain": True}],
    }}
    paper = {"tenant_id": "t", "subject_id": "sub", "structured_qa": rubric,
             "rubric_source": "official", "question_structure": {}}
    settings = SimpleNamespace(per_question_stage2_enabled=False, per_question_stage2_concurrency=5,
                               rate_limit_handwritten_evaluation_per_hour=10)
    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=settings), \
         patch("app.services.evaluation_stage2_runner.deepseek_stage2") as call:
        outcome = run_stage2(Mock(), submission, paper, force_review=True)
    call.assert_not_called()
    assert outcome.questions[0]["marks_obtained"] == 1
    assert outcome.requires_review is True


def _runner_settings(grouped=True):
    return SimpleNamespace(per_question_stage2_enabled=grouped,
                           per_question_stage2_concurrency=2,
                           rate_limit_handwritten_evaluation_per_hour=10)


def _runner_service():
    service = Mock()
    service.rpc.return_value.execute.return_value = SimpleNamespace(
        data={"allowed": True, "retry_after_seconds": 0, "remaining": 9}
    )
    return service


def _runner_inputs(unmatched=False):
    extraction = {"text_answers": [
        {"question_ref": "Q1", "raw_text": "one"},
        {"question_ref": "Q2", "raw_text": "two"},
    ]}
    if unmatched:
        extraction["text_answers"].append({"question_ref": "Q9", "raw_text": "orphan"})
    return (
        {"id": "s", "tenant_id": "t", "student_id": "u", "stage1_extraction": extraction},
        {"tenant_id": "t", "subject_id": "sub", "structured_qa": [question("Q1"), question("Q2")],
         "rubric_source": "official", "question_structure": {}},
    )


def _compiled(question_row):
    return ([{"question_ref": question_row["question_ref"], "question_text": "",
              "marks_obtained": 1, "marks_possible": 1, "not_attempted": False,
              "not_evaluated": False, "not_counted": False, "mapping_status": "matched",
              "feedback": "", "student_guidance": {}, "student_answer_excerpt": "answer",
              "handwriting_legibility": "clear", "grading_confidence": 1,
              "criteria_breakdown": []}], False, {"sequence": 1})


def test_grouped_mode_unmatched_evidence_falls_back_before_sending():
    submission, paper = _runner_inputs(unmatched=True)
    call = Mock(side_effect=lambda service, payload, context, route, sequence: _compiled(payload["questions"][0]))
    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=_runner_settings()), \
         patch("app.services.evaluation_stage2_runner._call", call):
        run_stage2(_runner_service(), submission, paper)
    assert call.call_count == 1
    assert call.call_args.args[3] == "whole_paper"
    assert len(call.call_args.args[1]["questions"]) == 2


def test_grouped_mode_keeps_valid_sibling_when_one_response_is_malformed():
    submission, paper = _runner_inputs()

    def grade(service, payload, context, route, sequence):
        if payload["questions"][0]["question_ref"] == "Q2":
            raise Stage2PermanentError("malformed received response")
        return _compiled(payload["questions"][0])

    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=_runner_settings()), \
         patch("app.services.evaluation_stage2_runner._call", side_effect=grade):
        outcome = run_stage2(_runner_service(), submission, paper)
    assert [row["not_evaluated"] for row in outcome.questions] == [False, True]
    assert outcome.requires_review


def test_grouped_mode_distinguishes_no_response_from_unusable_responses():
    submission, paper = _runner_inputs()
    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=_runner_settings()), \
         patch("app.services.evaluation_stage2_runner._call", side_effect=Stage2RetryableError("no response")), \
         pytest.raises(Stage2RetryableError):
        run_stage2(_runner_service(), submission, paper)
    with patch("app.services.evaluation_stage2_runner.resolve_paper_profile", return_value=None), \
         patch("app.services.evaluation_stage2_runner.get_settings", return_value=_runner_settings()), \
         patch("app.services.evaluation_stage2_runner._call", side_effect=Stage2PermanentError("received but unusable")), \
         pytest.raises(Stage2PermanentError):
        run_stage2(_runner_service(), submission, paper)
