from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.generated_papers import GeneratePaperRequest, get_generated_paper, start_generated_paper
from app.lib.auth import CurrentProfile
from app.services.paper_generation import AIPaperPlan, AISection, generate_paper
from tests.test_faculty_pilot_safety import Service


TENANT = str(uuid4())
OTHER = str(uuid4())
TEACHER = str(uuid4())
LEVEL = str(uuid4())
SUBJECT = str(uuid4())
PAPER = str(uuid4())
PROFILE = CurrentProfile(
    user_id=TEACHER,
    tenant_id=TENANT,
    role="teacher",
    tenant_feature_flags={"faculty_jobs": True},
)
SETTINGS = SimpleNamespace(
    paper_bank_enabled=True,
    faculty_jobs_enabled=True,
    quiz_generation_provider="deepseek",
)


def _question(identifier, marks, tenant=TENANT, kind="mcq_single"):
    return {
        "id": identifier,
        "tenant_id": tenant,
        "paper_type": "pyq",
        "subject_id": SUBJECT,
        "chapter_id": "chapter",
        "exam": "Exam",
        "year": "2026",
        "type": kind,
        "question_text": f"Question {identifier}",
        "options": [],
        "correct_answer": "answer",
        "explanation": "why",
        "marks": marks,
        "model_answer": None,
        "answer_summary": None,
    }


def _job(mode="candidate_ai"):
    return {
        "id": "job-1",
        "tenant_id": TENANT,
        "created_by": TEACHER,
        "kind": "generate_paper",
        "request": {
            "generated_paper_id": PAPER,
            "course_level_id": LEVEL,
            "subject_id": SUBJECT,
            "mode": mode,
            "requested_total_marks": 10,
            "question_count": 2,
            "chapter_ids": [],
            "question_types": [],
        },
    }


def _service():
    return Service({
        "generated_papers": [{
            "id": PAPER, "tenant_id": TENANT, "created_by": TEACHER,
            "course_level_id": LEVEL, "subject_id": SUBJECT, "status": "pending",
        }],
        "paper_questions": [
            _question("q1", 5), _question("q2", 5), _question("q3", 4),
            _question("other-secret", 10, tenant=OTHER),
        ],
    })


def _profile():
    return {
        "course_level_id": LEVEL,
        "exam_body": "Example Board",
        "level": "Level 1",
        "paper": "Accounting",
        "assessment_year": "2026",
        "framework": "Local GAAP",
        "format_config": {
            "sections": [{"name": "Objective", "question_type": "mcq_single", "count": 2}],
            "instructions": ["1. Answer all questions"],
            "numbering_style": "q_numeric",
            "duration_minutes": 60,
            "locale": "en-IN",
            "currency_symbol": "₹",
        },
    }


def test_candidate_ai_wrong_total_is_corrected_locally_and_tenant_isolated():
    service = _service()
    wrong = AIPaperPlan(
        instructions=["Wrong total"],
        sections=[AISection(name="Objective", question_ids=["q3"])],
        total_marks=10,
    )
    with patch("app.services.paper_generation.resolve_paper_profile", return_value=_profile()), \
         patch("app.services.paper_generation._complete_plan", return_value=(wrong, "mock")), \
         patch("app.services.paper_generation.get_settings", return_value=SETTINGS):
        result = generate_paper(service, _job())

    assert result["provider"] == "local_exact_correction"
    stored = service.tables["generated_papers"][0]
    assert stored["status"] == "ready"
    assert set(stored["selected_question_ids"]) == {"q1", "q2"}
    assert "other-secret" not in stored["selected_question_ids"]
    assert stored["paper_payload"]["total_marks"] == 10


def test_candidate_ai_fails_when_no_exact_correction_exists():
    service = _service()
    service.tables["paper_questions"] = [_question("q3", 4)]
    wrong = AIPaperPlan(
        instructions=[], sections=[AISection(name="Only", question_ids=["q3"])], total_marks=10
    )
    with patch("app.services.paper_generation.resolve_paper_profile", return_value=_profile()), \
         patch("app.services.paper_generation._complete_plan", return_value=(wrong, "mock")), \
         patch("app.services.paper_generation.get_settings", return_value=SETTINGS):
        with pytest.raises(Exception, match="formatting failed"):
            generate_paper(service, _job())


def test_start_requires_teacher_and_passes_server_profile_to_atomic_enqueue():
    body = GeneratePaperRequest(
        request_key=uuid4(), course_level_id=LEVEL, subject_id=SUBJECT,
        mode="exact_mark", requested_total_marks=10, question_count=2,
    )
    with patch("app.api.generated_papers.get_settings", return_value=SETTINGS), \
         patch("app.api.generated_papers.enqueue_generated_paper", return_value={"id": "job"}) as enqueue:
        assert start_generated_paper(body, PROFILE) == {"id": "job"}
    assert enqueue.call_args.args[0] == PROFILE
    with pytest.raises(HTTPException) as error:
        start_generated_paper(body, PROFILE.model_copy(update={"role": "student"}))
    assert error.value.status_code == 403


def test_request_rejects_marks_outside_the_half_mark_grid():
    with pytest.raises(ValueError, match="whole or half marks"):
        GeneratePaperRequest(
            request_key=uuid4(), course_level_id=LEVEL, subject_id=SUBJECT,
            mode="exact_mark", requested_total_marks=10.25, question_count=2,
        )


def test_get_is_scoped_to_tenant_and_teacher_owner():
    service = _service()
    with patch("app.api.generated_papers.get_settings", return_value=SETTINGS), \
         patch("app.api.generated_papers.get_service_client", return_value=service):
        assert get_generated_paper(PAPER, PROFILE)["id"] == PAPER
        with pytest.raises(HTTPException) as error:
            get_generated_paper(PAPER, PROFILE.model_copy(update={"user_id": "other-teacher"}))
    assert error.value.status_code == 404
