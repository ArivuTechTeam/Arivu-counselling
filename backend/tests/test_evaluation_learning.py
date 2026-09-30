from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.handwritten_learning import _target_student, weak_areas
from app.lib.auth import CurrentProfile
from app.services.evaluation_learning import (
    LearningContext, _signature, analytics_values, build_mistake_specs,
    current_evaluation_ids, resolve_chapter_name,
)
from app.services.evaluation_worker import _run_learning_follow_on


def context(questions, *, rubric=None, chapters=None):
    return LearningContext(
        tenant_id="tenant", evaluation_id="evaluation", student_id="student",
        subject_id="subject", paper_id="paper", overall_feedback="Overall feedback",
        questions=questions, rubric=rubric or [], chapter_names=chapters or [],
    )


def result(**overrides):
    row = {
        "id": "qr", "question_ref": "Q1", "question_text": "Contract Act question",
        "marks_obtained": 2, "marks_possible": 5, "not_attempted": False,
        "not_evaluated": False, "not_counted": False, "feedback": "Incomplete",
        "student_answer_excerpt": "answer", "criteria_breakdown": [],
    }
    row.update(overrides)
    return row


def test_mistake_skip_rules_and_blank_creates_exactly_one():
    rows = [
        result(id="ignored-choice", not_counted=True),
        result(id="unsafe", not_evaluated=True),
        result(id="full", marks_obtained=5),
        result(id="blank", not_attempted=True, marks_obtained=0,
               criteria_breakdown=[{"criterion": "One", "marks_available": 2, "marks_awarded": 0},
                                   {"criterion": "Two", "marks_available": 3, "marks_awarded": 0}]),
    ]
    mistakes = build_mistake_specs(context(rows))
    assert len(mistakes) == 1
    assert mistakes[0]["question_result_id"] == "blank"
    assert mistakes[0]["category"] == "not_attempted"
    assert mistakes[0]["marks_lost"] == 5


def test_proportional_allocation_residual_is_exact_and_categories_fall_back():
    rows = [result(criteria_breakdown=[
        {"criterion": "Calculation figure", "marks_available": 2, "marks_awarded": 1,
         "comment": "Figure error"},
        {"criterion": "Working method", "marks_available": 3, "marks_awarded": 1,
         "category": "unknown"},
    ])]
    mistakes = build_mistake_specs(context(rows))
    assert sum(row["marks_lost"] for row in mistakes) == 3
    assert [row["category"] for row in mistakes] == ["calculation", "step_loss"]
    assert mistakes[0]["description"] == "Figure error"


@pytest.mark.parametrize(("lost", "severity"), [(.9, "minor"), (1, "moderate"), (2.9, "moderate"), (3, "major")])
def test_severity_boundaries(lost, severity):
    row = result(marks_possible=lost, marks_obtained=0,
                 criteria_breakdown=[{"criterion": "Concept", "marks_available": lost, "marks_awarded": 0}])
    assert build_mistake_specs(context([row]))[0]["severity"] == severity


def test_chapter_resolution_is_rubric_then_longest_subject_chapter_then_other():
    chapters = ["Contract", "Contract Act", "Tax"]
    assert resolve_chapter_name("Rubric topic", "Contract Act", chapters) == "Rubric topic"
    assert resolve_chapter_name("", "Question under the Contract Act", chapters) == "Contract Act"
    assert resolve_chapter_name("", "Unrelated question", chapters) == "Other topics"


def test_signature_is_normalized_stable_sha256():
    left = _signature("Contract Act", "Conceptual", "Offer & Acceptance")
    right = _signature(" contract-act ", "CONCEPTUAL", "offer acceptance")
    assert left == right
    assert len(left) == 64


@pytest.mark.parametrize(("score", "level"), [(34.99, "beginner"), (35, "improving"),
                                                (50, "proficient"), (65, "advanced"),
                                                (80, "exam_ready")])
def test_analytics_level_boundaries(score, level):
    assert analytics_values([{"id": "e", "percentage": score, "created_at": "2026-01-01"}])["current_level"] == level


def test_analytics_history_and_mean_improvement():
    values = analytics_values([
        {"id": "e3", "percentage": 70, "created_at": "2026-03-01"},
        {"id": "e1", "percentage": 40, "created_at": "2026-01-01"},
        {"id": "e2", "percentage": 50, "created_at": "2026-02-01"},
    ])
    assert values["total_attempts"] == 3
    assert values["avg_percentage"] == pytest.approx(53.33)
    assert values["best_percentage"] == 70
    assert values["latest_percentage"] == 70
    assert values["improvement_rate"] == 15
    assert [row["evaluation_id"] for row in values["score_history"]] == ["e1", "e2", "e3"]
    assert not any(key in values for key in (
        "weak_chapters", "top_mistake_categories", "presentation_scores", "streak_count",
    ))


def test_current_mistakes_use_latest_submission_per_paper_not_latest_evaluation_time():
    papers = [{"id": "paper", "subject_id": "subject"}]
    submissions = [
        {"id": "old-sub", "evaluation_paper_id": "paper", "created_at": "2026-01-01"},
        {"id": "new-sub", "evaluation_paper_id": "paper", "created_at": "2026-02-01"},
    ]
    evaluations = [
        {"id": "old-eval", "submission_id": "old-sub", "created_at": "2026-03-01"},
        {"id": "new-eval", "submission_id": "new-sub", "created_at": "2026-02-01"},
    ]
    with patch("app.services.evaluation_learning.select_all", side_effect=[papers, submissions]), \
         patch("app.services.evaluation_learning.select_all_in", return_value=evaluations):
        assert current_evaluation_ids(
            Mock(), tenant_id="tenant", student_id="student", subject_id="subject",
        ) == ["new-eval"]


def test_revision_sql_locks_student_and_uses_distinct_current_papers():
    sql = (Path(__file__).parents[2] / "migrations" /
           "migration-82-handwritten-learning.sql").read_text()
    normalized = " ".join(sql.lower().split())
    assert "p.role='student' for update" in normalized
    assert "count(distinct r.evaluation_paper_id)>=2" in normalized
    assert normalized.count(
        "row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc)"
    ) == 3
    analytics_table = normalized.split(
        "create table if not exists public.handwritten_student_analytics(", 1
    )[1].split(");", 1)[0]
    assert not any(column in analytics_table for column in (
        "weak_chapters", "top_mistake_categories", "presentation_scores", "streak_count",
    ))


def test_learning_failures_are_isolated_after_phase_c_commit():
    service = Mock()
    with patch("app.services.evaluation_worker.create_mistakes", side_effect=RuntimeError("broken")), \
         patch("app.services.evaluation_worker.reconcile_revision_items") as reconcile, \
         patch("app.services.evaluation_worker.update_student_analytics") as analytics:
        _run_learning_follow_on(
            service, evaluation_id="evaluation",
            submission={"tenant_id": "tenant", "student_id": "student"},
            paper={"subject_id": "subject"},
        )
    reconcile.assert_called_once()
    analytics.assert_called_once()


def profile(role, tenant="tenant", user="student"):
    return CurrentProfile(user_id=user, tenant_id=tenant, role=role)


def test_student_scope_rejects_other_student_and_teacher_checks_target_tenant():
    service = Mock()
    with pytest.raises(HTTPException) as error:
        _target_student(service, profile("student"), uuid4())
    assert error.value.status_code == 403

    target = uuid4()
    service.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(data=None)
    with pytest.raises(HTTPException) as error:
        _target_student(service, profile("teacher", user="teacher"), target)
    assert error.value.status_code == 404


def test_weak_areas_are_computed_live_without_analytics_gap_fields():
    service = Mock()
    revision_query = service.table.return_value.select.return_value
    revision_query.eq.return_value = revision_query
    revision_query.order.return_value = revision_query
    revision_query.range.return_value.execute.return_value = SimpleNamespace(data=[{
        "subject_id": "subject", "chapter": "Tax", "title": "Tax",
        "marks_at_risk": 4, "source_count": 2, "priority": "high",
        "last_seen_at": "2026-01-01",
    }])
    with patch("app.api.handwritten_learning.get_service_client", return_value=service), \
         patch("app.api.handwritten_learning.require_evaluation_enabled"), \
         patch("app.api.handwritten_learning.current_mistakes", return_value=[
             {"category": "conceptual", "marks_lost": 2},
             {"category": "conceptual", "marks_lost": 1},
             {"category": "calculation", "marks_lost": 4},
         ]):
        output = weak_areas(profile=profile("student"))
    assert output["weak_chapters"][0]["chapter"] == "Tax"
    assert output["mistake_patterns"] == [
        {"category": "calculation", "count": 1, "total_marks_lost": 4.0},
        {"category": "conceptual", "count": 2, "total_marks_lost": 3.0},
    ]
