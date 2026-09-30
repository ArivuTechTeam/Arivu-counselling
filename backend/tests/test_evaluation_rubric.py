from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.evaluation_rubric import (
    RubricPermanentError,
    RubricOutcome,
    build_rubric,
    validate_rubric,
)
from app.services.evaluation_worker import run_one


PAPER_TEXT = """Q1 State the matching principle. (2 marks)
Q2 Select the correct option. A. Debit B. Credit (1 mark)
Q3 Attempt the calculation. (2 marks)
Q4 Attempt the calculation. (2 marks)
Q5 Attempt the calculation. (2 marks)"""


def question(ref="Q1", text="Q1 State the matching principle. (2 marks)", marks=2):
    return {
        "question_ref": ref,
        "question_text": text,
        "topic": "Accounting principles",
        "suggested_answer": "Match expenses with related revenue.",
        "question_type": "descriptive",
        "options": [],
        "correct_option": "",
        "expected_answer_points": ["Expenses follow related revenue"],
        "marks": marks,
        "marks_source": "printed",
        "parent_question_ref": ref,
        "parent_total_marks": marks,
        "evaluation_criteria": [
            {"criterion": "States the matching principle", "marks": marks,
             "category": "conceptual"}
        ],
    }


def candidate(rows=None, structure=None):
    return {
        "questions": rows or [question()],
        "paper_structure": structure or {
            "compulsory": ["Q1"], "optional_groups": [],
            "printed_required_marks": 2, "configured_total_marks": 2,
            "structure_adjusted": False, "requires_admin_review": False,
            "adjustment_reason": "",
        },
    }


def errors(value, paper=PAPER_TEXT, total=2):
    return validate_rubric(value, paper, total).errors


def test_valid_rubric_preserves_atomic_question_and_exact_marks():
    result = validate_rubric(candidate(), PAPER_TEXT, 2)
    assert result.errors == []
    assert result.questions[0]["question_text"] == question()["question_text"]
    assert result.questions[0]["evaluation_criteria"][0]["marks"] == 2


@pytest.mark.parametrize("mutate, expected", [
    (lambda q: q.update(question_text="Paraphrased question"), "verbatim"),
    (lambda q: q.update(marks=1.25), "0.5 increments"),
    (lambda q: q.update(marks_source="unknown"), "unverified"),
    (lambda q: q.update(parent_question_ref=""), "parent mark metadata"),
    (lambda q: q.update(evaluation_criteria=[
        {"criterion": "accuracy", "marks": 2, "category": "conceptual"}
    ]), "vague"),
    (lambda q: q.update(evaluation_criteria=[
        {"criterion": "Names matching", "marks": 0.25, "category": "conceptual"},
        {"criterion": "Explains matching", "marks": 1.75, "category": "application"},
    ]), "half-mark grid"),
    (lambda q: q.update(evaluation_criteria=[
        {"criterion": "Names matching", "marks": 1, "category": "conceptual"}
    ]), "sum exactly"),
    (lambda q: q.update(evaluation_criteria=[
        {"criterion": f"Specific component {index}", "marks": .5,
         "category": "conceptual"} for index in range(5)
    ]), "marks x 2"),
])
def test_invariant(mutate, expected):
    row = question(); mutate(row)
    assert any(expected in item for item in errors(candidate([row])))


def test_duplicate_refs_and_printed_marks_cannot_be_overwritten():
    duplicate = question()
    assert any("duplicate question_ref" in item for item in errors(candidate([question(), duplicate])))
    overwritten = question(marks=1)
    overwritten["parent_total_marks"] = 1
    overwritten["evaluation_criteria"][0]["marks"] = 1
    assert any("printed child marks" in item for item in errors(candidate([overwritten])))


def test_verified_parent_arithmetic_corrects_equal_split_and_rejects_guessing():
    rows = []
    for ref, text in (("Q3", "Q3 Attempt the calculation. (2 marks)"),
                      ("Q4", "Q4 Attempt the calculation. (2 marks)")):
        row = question(ref, text, 2)
        row.update(marks_source="derived_from_parent", parent_question_ref="P", parent_total_marks=4)
        rows.append(row)
    valid = validate_rubric(candidate(rows), PAPER_TEXT, 4)
    assert valid.errors == []
    third = question("Q5", "Q5 Attempt the calculation. (2 marks)", 2)
    third.update(marks_source="derived_from_parent", parent_question_ref="P", parent_total_marks=4)
    invalid = rows + [third]
    for row in invalid:
        row["parent_total_marks"] = 4
    assert any("unverified child allocation" in item for item in errors(candidate(invalid), total=4))


def test_mcq_requires_unique_options_key_and_one_full_mark_criterion():
    row = question("Q2", "Q2 Select the correct option. A. Debit B. Credit (1 mark)", 1)
    row.update(
        question_type="mcq_single",
        options=[{"label": "A", "text": "Debit"}, {"label": "B", "text": "Credit"}],
        correct_option="B",
        evaluation_criteria=[{"criterion": "Selects option B", "marks": 1,
                              "category": "conceptual"}],
    )
    assert errors(candidate([row]), total=1) == []
    row["evaluation_criteria"] = [
        {"criterion": "Identifies debit", "marks": .5, "category": "conceptual"},
        {"criterion": "Identifies credit", "marks": .5, "category": "conceptual"},
    ]
    assert any("exactly one full-mark" in item for item in errors(candidate([row]), total=1))


def test_pick_is_corrected_only_when_one_whole_number_solution_is_provable():
    rows = [question("Q1", question()["question_text"], 2)]
    for ref in ("Q3", "Q4", "Q5"):
        rows.append(question(ref, f"{ref} Attempt the calculation. (2 marks)", 2))
    structure = {
        "compulsory": ["Q1"],
        "optional_groups": [{"label": "Q3-Q5", "printed_pick": 2, "pick": 2,
                             "questions": ["Q3", "Q4", "Q5"]}],
        "printed_required_marks": 6, "configured_total_marks": 4,
        "structure_adjusted": False, "requires_admin_review": False,
        "adjustment_reason": "",
    }
    validated = validate_rubric(candidate(rows, structure), PAPER_TEXT, 4)
    assert validated.errors == []
    assert validated.question_structure["optional_groups"][0]["pick"] == 1
    assert validated.question_structure["structure_adjusted"] is True

    ambiguous = deepcopy(structure)
    ambiguous["optional_groups"].append({
        "label": "Other", "printed_pick": 1, "pick": 2, "questions": ["Q3", "Q4"]
    })
    reviewed = validate_rubric(candidate(rows, ambiguous), PAPER_TEXT, 4).question_structure
    assert reviewed["requires_admin_review"] is True
    assert all(group["pick"] == group["printed_pick"] for group in reviewed["optional_groups"])


def test_narrow_paper_total_copy_is_recovered_and_criteria_rescaled():
    text = "Q1 Explain alpha.\nQ2 Explain beta."
    rows = []
    for ref, question_text in (("Q1", "Q1 Explain alpha."), ("Q2", "Q2 Explain beta.")):
        row = question(ref, question_text, 4)
        row.update(
            marks_source="derived_from_parent",
            parent_question_ref=ref,
            parent_total_marks=4,
            evaluation_criteria=[
                {"criterion": "Explains the governing principle", "marks": 2,
                 "category": "conceptual"},
                {"criterion": "Applies the governing principle", "marks": 2,
                 "category": "application"},
            ],
        )
        rows.append(row)
    result = validate_rubric(candidate(rows, {
        "compulsory": ["Q1", "Q2"], "optional_groups": [],
        "printed_required_marks": 0, "configured_total_marks": 4,
        "structure_adjusted": False, "requires_admin_review": False,
        "adjustment_reason": "",
    }), text, 4)
    assert result.errors == []
    assert [row["marks"] for row in result.questions] == [2, 2]
    assert {row["parent_question_ref"] for row in result.questions} == {"PAPER_TOTAL"}
    assert all(sum(item["marks"] for item in row["evaluation_criteria"]) == 2
               for row in result.questions)


def paper(answer_path="answer.pdf"):
    return {
        "id": "paper-a", "tenant_id": "tenant-a", "subject_id": "subject-a",
        "course_level_id": "level-a", "total_marks": 2,
        "question_paper_storage_path": "question.pdf",
        "suggested_answer_storage_path": answer_path,
        "question_paper_text": PAPER_TEXT.splitlines()[0],
        "suggested_answer_text": "Official: match expenses to revenue." if answer_path else "",
    }


def rubric_settings():
    return SimpleNamespace(handwritten_rubric_provider="gemini",
                           gemini_extraction_max_output_tokens=32000)


def test_official_and_ai_derived_generation_paths_and_prompt_tenant_context():
    generator = Mock(return_value=(candidate(), "gemini"))
    with patch("app.services.evaluation_rubric._context",
               return_value=("Accounts", "CA", "Foundation", "exam ICAI")), \
         patch("app.services.evaluation_rubric.get_settings", return_value=rubric_settings()):
        official = build_rubric(Mock(), paper(), generator=generator)
        derived = build_rubric(Mock(), paper(None), generator=generator)
    assert official.source == "official"
    assert derived.source == "ai_derived"
    assert "tenant-a" not in generator.call_args_list[0].args[1]
    assert "OFFICIAL SUGGESTED ANSWERS" in generator.call_args_list[0].args[1]
    assert "NO OFFICIAL SUGGESTED ANSWERS" in generator.call_args_list[1].args[1]


def test_one_semantic_repair_then_success_or_permanent_failure():
    bad = candidate(); bad["questions"][0]["marks"] = 1.25
    generator = Mock(side_effect=[(bad, "gemini"), (candidate(), "gemini")])
    with patch("app.services.evaluation_rubric._context", return_value=("", "", "", "")), \
         patch("app.services.evaluation_rubric.get_settings", return_value=rubric_settings()):
        assert build_rubric(Mock(), paper(), generator=generator).source == "official"
    assert generator.call_count == 2
    assert "BACKEND VALIDATION FEEDBACK" in generator.call_args_list[1].args[1]

    generator = Mock(side_effect=[(bad, "gemini"), (bad, "gemini")])
    with patch("app.services.evaluation_rubric._context", return_value=("", "", "", "")), \
         patch("app.services.evaluation_rubric.get_settings", return_value=rubric_settings()), \
         pytest.raises(RubricPermanentError):
        build_rubric(Mock(), paper(), generator=generator)
    assert generator.call_count == 2


def test_worker_runs_teacher_owned_rubric_lifecycle_and_persists_only_validated_output():
    job = {"id": "job-a", "kind": "build_rubric", "tenant_id": "tenant-a",
           "evaluation_paper_id": "paper-a", "owner_teacher_id": "teacher-a"}
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    outcome = RubricOutcome(candidate()["questions"], candidate()["paper_structure"],
                            "official", PAPER_TEXT, "Official answer")

    def generate(_service, _paper, **kwargs):
        kwargs["on_extracted"](outcome.question_text, outcome.answer_text)
        return outcome

    with patch("app.services.evaluation_worker._authorized_rubric", return_value=True), \
         patch("app.services.evaluation_worker._rubric_context", return_value=paper()), \
         patch("app.services.evaluation_worker.build_rubric", side_effect=generate):
        assert run_one(service, worker_id="worker-a") is True
    assert [call.args[0] for call in service.rpc.call_args_list] == [
        "claim_evaluation_job", "start_evaluation_job",
        "checkpoint_evaluation_rubric_texts", "finish_evaluation_rubric_job",
    ]
    persisted = service.rpc.call_args_list[-1].args[1]
    assert persisted["p_structured_qa"] == outcome.questions
    assert persisted["p_source"] == "official"
