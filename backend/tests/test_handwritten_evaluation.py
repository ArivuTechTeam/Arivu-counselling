import asyncio
import io
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.evaluation_papers import (
    create_evaluation_paper,
    delete_evaluation_paper,
    get_evaluation_paper,
    list_evaluation_papers,
    update_evaluation_paper,
)
from app.api.handwritten_submissions import (
    CreateSubmissionRequest,
    UploadIntentRequest,
    create_upload_intent,
    create_submission,
    finalize_upload_intent,
    get_answer_script_url,
    get_evaluation_report,
    get_stage2_artifacts,
    get_submission,
    list_paper_submissions,
    list_submissions,
    mark_submission_failed,
    MarkFailedRequest,
)
from app.lib.auth import CurrentProfile
from app.services.evaluation_stage1 import Stage1Outcome
from app.services.evaluation_worker import run_one
from tests.test_faculty_pilot_safety import Query, Service


TENANT = str(uuid4())
OTHER_TENANT = str(uuid4())
STUDENT = str(uuid4())
TEACHER = str(uuid4())
PAPER = str(uuid4())
INTENT = str(uuid4())
SUBMISSION = str(uuid4())
JOB = str(uuid4())
PDF = b"%PDF-1.7\nanswer"


def profile(role="student", *, tenant=TENANT, user=None):
    return CurrentProfile(
        user_id=user or (STUDENT if role == "student" else TEACHER),
        tenant_id=tenant,
        role=role,
        full_name="Arjun Student" if role == "student" else None,
        email="arjun@example.com" if role == "student" else None,
    )


def tables(intent_status="pending"):
    return {
        "tenants": [
            {"id": TENANT, "handwritten_evaluation_enabled": True},
            {"id": OTHER_TENANT, "handwritten_evaluation_enabled": True},
        ],
        "evaluation_papers": [
            {
                "id": PAPER,
                "tenant_id": TENANT,
                "course_level_id": str(uuid4()),
                "subject_id": str(uuid4()),
                "title": "Accounts mock",
                "question_paper_storage_path": "a/paper.pdf",
                "suggested_answer_storage_path": None,
                "total_marks": 100,
                "rubric_status": "not_started",
                "is_active": True,
                "generated_paper_id": None,
                "created_by": TEACHER,
                "created_at": datetime.now(UTC).isoformat(),
            },
            {
                "id": str(uuid4()),
                "tenant_id": OTHER_TENANT,
                "course_level_id": str(uuid4()),
                "subject_id": str(uuid4()),
                "title": "Other tenant secret",
                "question_paper_storage_path": "b/paper.pdf",
                "suggested_answer_storage_path": None,
                "total_marks": 80,
                "rubric_status": "not_started",
                "is_active": True,
                "generated_paper_id": None,
                "created_by": str(uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
            },
        ],
        "evaluation_upload_intents": [
            {
                "id": INTENT,
                "tenant_id": TENANT,
                "student_id": STUDENT,
                "evaluation_paper_id": PAPER,
                "storage_path": "a/student/answer.pdf",
                "original_filename": "answer.pdf",
                "content_type": "application/pdf",
                "expected_size": len(PDF),
                "status": intent_status,
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                "verified_at": None,
            }
        ],
    }


def test_teacher_paper_listing_is_tenant_scoped_and_flag_uses_dedicated_column():
    source = tables()
    assigned_subject = source["evaluation_papers"][0]["subject_id"]
    source["teacher_subjects"] = [{
        "tenant_id": TENANT,
        "teacher_id": TEACHER,
        "subject_id": assigned_subject,
    }]
    service = Service(source)
    with patch("app.api.evaluation_papers.get_service_client", return_value=service):
        response = asyncio.run(list_evaluation_papers(profile("teacher")))
    assert [str(paper.id) for paper in response.papers] == [PAPER]
    assert all("Other tenant" not in paper.title for paper in response.papers)

    service.tables["tenants"][0]["handwritten_evaluation_enabled"] = False
    # A general feature flag cannot turn this dedicated entitlement back on.
    service.tables["tenants"][0]["feature_flags"] = {"handwritten_evaluation": True}
    with patch("app.api.evaluation_papers.get_service_client", return_value=service), pytest.raises(HTTPException) as error:
        asyncio.run(list_evaluation_papers(profile("teacher")))
    assert error.value.status_code == 403


def test_teacher_paper_reads_are_limited_to_assigned_subjects():
    now = datetime.now(UTC).isoformat()
    subject_a, subject_b = str(uuid4()), str(uuid4())
    paper_a, paper_b = str(uuid4()), str(uuid4())
    base = {
        "tenant_id": TENANT,
        "course_level_id": str(uuid4()),
        "question_paper_storage_path": "tenant/paper.pdf",
        "suggested_answer_storage_path": "tenant/answers.pdf",
        "total_marks": 100,
        "rubric_status": "ready",
        "is_active": True,
        "generated_paper_id": None,
        "created_by": TEACHER,
        "created_at": now,
    }
    service = Service({
        "tenants": [{"id": TENANT, "handwritten_evaluation_enabled": True}],
        "teacher_subjects": [{
            "tenant_id": TENANT,
            "teacher_id": TEACHER,
            "subject_id": subject_a,
        }],
        "evaluation_papers": [
            {**base, "id": paper_a, "subject_id": subject_a, "title": "Subject A"},
            {**base, "id": paper_b, "subject_id": subject_b, "title": "Subject B"},
        ],
    })
    with patch("app.api.evaluation_papers.get_service_client", return_value=service):
        listed = asyncio.run(list_evaluation_papers(profile("teacher")))
        assert [str(row.id) for row in listed.papers] == [paper_a]
        with pytest.raises(HTTPException) as denied:
            asyncio.run(get_evaluation_paper(UUID(paper_b), profile("teacher")))
    assert denied.value.status_code == 404


def test_institution_admin_lists_every_paper_in_own_tenant():
    source = tables()
    source["evaluation_papers"].append({
        **source["evaluation_papers"][0],
        "id": str(uuid4()), "subject_id": str(uuid4()), "title": "Second subject",
        "question_paper_storage_path": "a/second.pdf",
    })
    service = Service(source)
    admin = profile("institution_admin")
    with patch("app.api.evaluation_papers.get_service_client", return_value=service):
        response = asyncio.run(list_evaluation_papers(admin))
    assert {paper.title for paper in response.papers} == {"Accounts mock", "Second subject"}


def test_paper_management_response_includes_display_metadata_and_detail_extraction():
    source = tables()
    paper = source["evaluation_papers"][0]
    course_id = str(uuid4())
    source["subjects"] = [{
        "id": paper["subject_id"], "tenant_id": TENANT,
        "course_id": course_id, "course_level_id": paper["course_level_id"],
        "name": "Business Laws",
    }]
    source["course_levels"] = [{
        "id": paper["course_level_id"], "tenant_id": TENANT,
        "course_id": course_id, "name": "Foundation",
    }]
    source["courses"] = [{"id": course_id, "tenant_id": TENANT, "name": "CA"}]
    source["handwritten_submissions"] = [
        {"id": str(uuid4()), "tenant_id": TENANT, "evaluation_paper_id": PAPER},
        {"id": str(uuid4()), "tenant_id": TENANT, "evaluation_paper_id": PAPER},
    ]
    paper.update({
        "question_paper_text": "Question No. 1 is compulsory.",
        "suggested_answer_text": "Apply the relevant provision.",
        "structured_qa": [{"question_ref": "1(a)", "question_text": "Explain."}],
        "rubric_source": "official",
        "rubric_error": "",
    })
    service = Service(source)
    with patch("app.api.evaluation_papers.get_service_client", return_value=service), \
         patch("app.api.evaluation_papers.signed_url", return_value="https://signed.example/paper"):
        listed = asyncio.run(list_evaluation_papers(profile("institution_admin"))).papers[0]
        detail = asyncio.run(get_evaluation_paper(UUID(PAPER), profile("institution_admin")))

    assert (listed.course_name, listed.level_name, listed.subject_name) == (
        "CA", "Foundation", "Business Laws"
    )
    assert listed.submission_count == 2
    assert listed.has_suggested_answer is False
    # Large extracted fields remain detail-only, like ExamApp's lightweight list.
    assert listed.question_paper_text is None
    assert detail.question_paper_text == "Question No. 1 is compulsory."
    assert detail.suggested_answer_text == "Apply the relevant provision."
    assert detail.structured_qa[0]["question_ref"] == "1(a)"


def test_paper_update_delete_are_teacher_subject_scoped_and_admin_tenant_wide():
    class DeleteQuery(Query):
        deleting = False

        def delete(self):
            self.deleting = True
            return self

        def execute(self):
            if not self.deleting:
                return super().execute()
            rows = self.service.tables.setdefault(self.table, [])
            matches = [row for row in rows if all(check(row) for check in self.filters)]
            self.service.tables[self.table] = [row for row in rows if row not in matches]
            return SimpleNamespace(data=deepcopy(matches))

    class DeleteService(Service):
        def table(self, name):
            return DeleteQuery(self, name)

    source = tables()
    source["teacher_subjects"] = []
    service = DeleteService(source)
    teacher = profile("teacher")
    with patch("app.api.evaluation_papers.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as update_denied:
            asyncio.run(update_evaluation_paper(UUID(PAPER), title="Denied", profile=teacher))
        with pytest.raises(HTTPException) as delete_denied:
            asyncio.run(delete_evaluation_paper(UUID(PAPER), teacher))
    assert update_denied.value.status_code == 404
    assert delete_denied.value.status_code == 404

    admin = profile("institution_admin")
    with patch("app.api.evaluation_papers.get_service_client", return_value=service), \
         patch("app.api.evaluation_papers.signed_url", return_value="https://signed.example/paper"), \
         patch("app.api.evaluation_papers.delete_bytes") as delete_storage:
        updated = asyncio.run(
            update_evaluation_paper(UUID(PAPER), title="Admin updated", profile=admin)
        )
        assert updated.title == "Admin updated"
        asyncio.run(delete_evaluation_paper(UUID(PAPER), admin))
    assert not any(row["id"] == PAPER for row in service.tables["evaluation_papers"])
    delete_storage.assert_called_once_with(
        ["a/paper.pdf"], bucket="evaluation-papers"
    )


def test_paper_edit_reclassification_validates_target_subject_scope():
    source = tables()
    paper = source["evaluation_papers"][0]
    old_subject = paper["subject_id"]
    old_level = paper["course_level_id"]
    target_subject, target_level = str(uuid4()), str(uuid4())
    source["teacher_subjects"] = [{
        "tenant_id": TENANT,
        "teacher_id": TEACHER,
        "subject_id": old_subject,
    }]
    source["subjects"] = [
        {"id": old_subject, "tenant_id": TENANT, "course_level_id": old_level},
        {"id": target_subject, "tenant_id": TENANT, "course_level_id": target_level},
    ]
    service = Service(source)

    with patch("app.api.evaluation_papers.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(update_evaluation_paper(
                UUID(PAPER),
                course_level_id=UUID(target_level),
                subject_id=UUID(target_subject),
                profile=profile("teacher"),
            ))
    assert denied.value.status_code == 404

    with patch("app.api.evaluation_papers.get_service_client", return_value=service), \
         patch("app.api.evaluation_papers.signed_url", return_value="https://signed.example/paper"):
        updated = asyncio.run(update_evaluation_paper(
            UUID(PAPER),
            course_level_id=UUID(target_level),
            subject_id=UUID(target_subject),
            profile=profile("institution_admin"),
        ))
    assert str(updated.course_level_id) == target_level
    assert str(updated.subject_id) == target_subject


def test_finalize_rejects_size_mismatch_deletes_object_and_marks_failed():
    service = Service(tables())
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.download_bytes", return_value=PDF + b"extra"), \
         patch("app.api.handwritten_submissions.delete_bytes") as delete:
        with pytest.raises(HTTPException) as error:
            asyncio.run(finalize_upload_intent(UUID(INTENT), profile()))
    assert error.value.status_code == 400
    delete.assert_called_once_with("a/student/answer.pdf", bucket="evaluation-submissions")
    assert service.tables["evaluation_upload_intents"][0]["status"] == "failed"


def test_finalize_accepts_exact_size_and_magic_type():
    service = Service(tables())
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.download_bytes", return_value=PDF):
        result = asyncio.run(finalize_upload_intent(UUID(INTENT), profile()))
    assert result.status == "verified"
    assert service.tables["evaluation_upload_intents"][0]["status"] == "verified"
    assert service.tables["evaluation_upload_intents"][0]["verified_at"]


def test_submission_creation_replays_the_same_submission_and_job():
    payload = {
        "submission": {
            "id": SUBMISSION,
            "evaluation_paper_id": PAPER,
            "upload_intent_id": INTENT,
            "status": "queued",
            "created_at": datetime.now(UTC).isoformat(),
        },
        "job": {"id": JOB, "status": "queued"},
    }
    service = Mock()
    service.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = SimpleNamespace(
        data={"handwritten_evaluation_enabled": True}
    )
    service.rpc.return_value.execute.return_value = SimpleNamespace(data=payload)
    settings = SimpleNamespace(
        evaluation_jobs_enabled=True,
        handwritten_evaluation_attempts_per_paper=2,
    )
    body = CreateSubmissionRequest(upload_intent_id=UUID(INTENT))
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.get_settings", return_value=settings):
        first = asyncio.run(create_submission(body, profile()))
        replay = asyncio.run(create_submission(body, profile()))
    assert first.id == replay.id == UUID(SUBMISSION)
    assert first.job_id == replay.job_id == UUID(JOB)
    assert service.rpc.call_count == 2
    assert all(
        call.args[0] == "create_limited_handwritten_submission_job"
        for call in service.rpc.call_args_list
    )
    assert all(call.args[1]["p_limit"] == 2 for call in service.rpc.call_args_list)


def test_student_can_reload_submission_and_full_persisted_report_but_other_tenant_cannot():
    now = datetime.now(UTC).isoformat()
    service = Service({
        "tenants": [
            {"id": TENANT, "handwritten_evaluation_enabled": True},
            {"id": OTHER_TENANT, "handwritten_evaluation_enabled": True},
        ],
        "handwritten_submissions": [{
            "id": SUBMISSION, "tenant_id": TENANT, "student_id": STUDENT,
            "evaluation_paper_id": PAPER, "upload_intent_id": INTENT,
            "answer_script_path": "tenant/student/answer.pdf", "status": "evaluated",
            "created_at": now,
        }],
        "evaluation_jobs": [{
            "id": JOB, "submission_id": SUBMISSION, "status": "done",
        }],
        "evaluation_papers": [{
            "id": PAPER, "tenant_id": TENANT, "subject_id": "subject-1",
            "course_level_id": "level-1", "title": "Business Law Paper 2", "total_marks": 100,
        }],
        "subjects": [{"id": "subject-1", "tenant_id": TENANT, "course_id": "course-1", "course_level_id": "level-1", "name": "Business Law"}],
        "course_levels": [{"id": "level-1", "tenant_id": TENANT, "course_id": "course-1", "name": "Foundation"}],
        "courses": [{"id": "course-1", "tenant_id": TENANT, "name": "Chartered Accountant"}],
        "handwritten_evaluations": [{
            "id": "evaluation-1", "tenant_id": TENANT, "submission_id": SUBMISSION,
            "status": "completed", "total_marks_obtained": 64,
            "total_marks_possible": 100, "percentage": 64,
            "overall_feedback": "Good application; strengthen conclusions.",
            "strengths": ["Q1"], "areas_to_improve": ["Q2"], "created_at": now,
        }],
        "handwritten_question_evaluations": [{
            "evaluation_id": "evaluation-1", "tenant_id": TENANT,
            "question_ref": "Q1", "question_text": "Explain the rule.",
            "marks_obtained": 6, "marks_possible": 10,
            "not_attempted": False, "not_evaluated": False, "not_counted": False,
            "mapping_status": "matched", "feedback": "Apply the rule to the facts.",
            "student_guidance": {"what_you_did_well": "Correct rule", "improve_next": ["Conclude"]},
            "student_answer_excerpt": "The rule applies...", "handwriting_legibility": "clear",
            "grading_confidence": 1, "criteria_breakdown": [{
                "criterion_id": "c1", "criterion": "Rule", "marks_awarded": 6,
                "marks_available": 10, "correct_treatment": "Rule plus application",
            }], "created_at": now,
        }],
        "profiles": [{
            "id": STUDENT,
            "tenant_id": TENANT,
            "role": "student",
            "full_name": "Arjun Student",
        }],
        "teacher_subjects": [{
            "tenant_id": TENANT,
            "teacher_id": TEACHER,
            "subject_id": "subject-1",
        }],
    })
    service.auth = SimpleNamespace(admin=SimpleNamespace(
        get_user_by_id=lambda user_id: SimpleNamespace(
            user=SimpleNamespace(id=user_id, email="arjun@example.com")
        )
    ))
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.signed_url", return_value="https://signed.example/answer"):
        submissions = asyncio.run(list_submissions(profile()))
        report = asyncio.run(get_evaluation_report(UUID(SUBMISSION), profile()))
    assert submissions.submissions[0].job_status == "done"
    assert submissions.submissions[0].report_available is True
    assert submissions.submissions[0].paper_title == "Business Law Paper 2"
    assert submissions.submissions[0].subject_name == "Business Law"
    assert submissions.submissions[0].marks_obtained == 64
    assert submissions.submissions[0].marks_possible == 100
    assert report.total_score == 64
    assert report.paper.subject == "Business Law"
    assert report.student.name == "Arjun Student"
    assert report.student.email == "arjun@example.com"
    assert report.answer_script_url == "https://signed.example/answer"
    assert report.questions[0].criteria_breakdown[0]["correct_treatment"] == "Rule plus application"

    teacher = CurrentProfile(
        user_id=TEACHER,
        tenant_id=TENANT,
        role="teacher",
        full_name="Teacher Requester",
        email="teacher@example.com",
    )
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.signed_url", return_value="https://signed.example/answer"):
        teacher_report = asyncio.run(get_evaluation_report(UUID(SUBMISSION), teacher))
    assert teacher_report.student.name == "Arjun Student"
    assert teacher_report.student.email == "arjun@example.com"
    assert teacher_report.student.name != teacher.full_name
    assert teacher_report.student.email != teacher.email

    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         pytest.raises(HTTPException) as denied:
        asyncio.run(get_evaluation_report(UUID(SUBMISSION), profile(tenant=OTHER_TENANT)))
    assert denied.value.status_code == 404


def test_teacher_cannot_retrieve_unassigned_subject_submission_or_report():
    subject_a, subject_b = str(uuid4()), str(uuid4())
    paper_b, submission_b = str(uuid4()), str(uuid4())
    now = datetime.now(UTC).isoformat()
    service = Service({
        "tenants": [{"id": TENANT, "handwritten_evaluation_enabled": True}],
        "teacher_subjects": [{
            "tenant_id": TENANT,
            "teacher_id": TEACHER,
            "subject_id": subject_a,
        }],
        "evaluation_papers": [{
            "id": paper_b,
            "tenant_id": TENANT,
            "subject_id": subject_b,
        }],
        "handwritten_submissions": [{
            "id": submission_b,
            "tenant_id": TENANT,
            "student_id": STUDENT,
            "evaluation_paper_id": paper_b,
            "upload_intent_id": str(uuid4()),
            "answer_script_path": "tenant/student/answer.pdf",
            "status": "evaluated",
            "error_message": None,
            "created_at": now,
        }],
    })
    teacher = profile("teacher")
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as submission_denied:
            asyncio.run(get_submission(UUID(submission_b), teacher))
        with pytest.raises(HTTPException) as report_denied:
            asyncio.run(get_evaluation_report(UUID(submission_b), teacher))
    assert submission_denied.value.status_code == 404
    assert report_denied.value.status_code == 404


def test_teacher_lists_only_assigned_paper_submissions_and_opens_answer_sheet():
    subject_a, subject_b = str(uuid4()), str(uuid4())
    paper_a, paper_b = str(uuid4()), str(uuid4())
    submission_a, submission_b = str(uuid4()), str(uuid4())
    now = datetime.now(UTC).isoformat()
    service = Service({
        "tenants": [{"id": TENANT, "handwritten_evaluation_enabled": True}],
        "teacher_subjects": [{
            "tenant_id": TENANT, "teacher_id": TEACHER, "subject_id": subject_a,
        }],
        "evaluation_papers": [
            {"id": paper_a, "tenant_id": TENANT, "subject_id": subject_a,
             "course_level_id": "level-1", "title": "Assigned paper"},
            {"id": paper_b, "tenant_id": TENANT, "subject_id": subject_b,
             "course_level_id": "level-1", "title": "Hidden paper"},
        ],
        "handwritten_submissions": [
            {"id": submission_a, "tenant_id": TENANT, "student_id": STUDENT,
             "evaluation_paper_id": paper_a, "upload_intent_id": str(uuid4()),
             "answer_script_path": "tenant/student/assigned.pdf", "status": "queued",
             "error_message": None, "created_at": now},
            {"id": submission_b, "tenant_id": TENANT, "student_id": str(uuid4()),
             "evaluation_paper_id": paper_b, "upload_intent_id": str(uuid4()),
             "answer_script_path": "tenant/student/hidden.pdf", "status": "queued",
             "error_message": None, "created_at": now},
        ],
        "profiles": [{"id": STUDENT, "tenant_id": TENANT,
                      "role": "student", "full_name": "Arjun Student"}],
        "evaluation_jobs": [],
        "handwritten_evaluations": [],
    })
    service.auth = SimpleNamespace(admin=SimpleNamespace(
        get_user_by_id=lambda user_id: SimpleNamespace(
            user=SimpleNamespace(id=user_id, email="arjun@example.com")
        )
    ))
    teacher = profile("teacher")
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.signed_url", return_value="https://signed.example/assigned"):
        listed = asyncio.run(list_paper_submissions(UUID(paper_a), teacher))
        answer = asyncio.run(get_answer_script_url(UUID(submission_a), teacher))
        with pytest.raises(HTTPException) as paper_denied:
            asyncio.run(list_paper_submissions(UUID(paper_b), teacher))
        with pytest.raises(HTTPException) as answer_denied:
            asyncio.run(get_answer_script_url(UUID(submission_b), teacher))

    assert len(listed.submissions) == 1
    assert listed.submissions[0].student_name == "Arjun Student"
    assert listed.submissions[0].student_email == "arjun@example.com"
    assert str(listed.submissions[0].student_id) == STUDENT
    assert answer.url == "https://signed.example/assigned"
    assert paper_denied.value.status_code == 404
    assert answer_denied.value.status_code == 404


def test_worker_persists_stage1_only_after_authorization_recheck():
    job = {
        "id": JOB,
        "tenant_id": TENANT,
        "submission_id": SUBMISSION,
        "owner_student_id": STUDENT,
        "attempts": 1,
    }
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    outcome = Stage1Outcome({"text_answers": []}, "a/student/answer.pdf", {}, False)
    with patch("app.services.evaluation_worker._authorized_submission", return_value=True) as authorized, \
         patch("app.services.evaluation_worker._stage1_context", return_value=({"id": SUBMISSION}, {"id": PAPER})), \
         patch("app.services.evaluation_worker.run_stage1", return_value=outcome) as stage1:
        assert run_one(service, worker_id="worker") is True
    authorized.assert_called_once_with(service, job)
    stage1.assert_called_once()
    assert [call.args[0] for call in service.rpc.call_args_list] == [
        "claim_evaluation_job",
        "start_evaluation_job",
        "finish_evaluation_stage1_job",
    ]


def test_stub_worker_fails_closed_on_owner_or_tenant_mismatch():
    job = {
        "id": JOB,
        "tenant_id": TENANT,
        "submission_id": SUBMISSION,
        "owner_student_id": STUDENT,
        "attempts": 1,
    }
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    with patch("app.services.evaluation_worker._authorized_submission", return_value=False):
        assert run_one(service, worker_id="worker") is True
    assert [call.args[0] for call in service.rpc.call_args_list] == [
        "claim_evaluation_job",
        "fail_evaluation_job",
    ]
    assert service.rpc.call_args_list[-1].args[1]["p_retryable"] is False


def test_worker_watchdog_fences_a_hung_job_then_reaches_hard_exit():
    job = {
        "id": JOB, "tenant_id": TENANT, "submission_id": SUBMISSION,
        "owner_student_id": STUDENT, "attempts": 1,
    }
    service = Mock()
    service.rpc.side_effect = [
        Mock(execute=Mock(return_value=SimpleNamespace(data=job))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
        Mock(execute=Mock(return_value=SimpleNamespace(data=True))),
    ]
    watchdog_service = Mock()
    watchdog_service.rpc.return_value.execute.return_value = SimpleNamespace(
        data={"changed": True, "retrying": True}
    )
    exits: list[int] = []
    outcome = Stage1Outcome({"text_answers": []}, "answer.pdf", {}, False)

    def slow_stage1(*_args, **_kwargs):
        time.sleep(0.04)
        return outcome

    with patch("app.services.evaluation_worker._authorized_submission", return_value=True), \
         patch("app.services.evaluation_worker._stage1_context", return_value=(
             {"id": SUBMISSION}, {"id": PAPER, "rubric_status": "not_started"}
         )), \
         patch("app.services.evaluation_worker.run_stage1", side_effect=slow_stage1), \
         patch("app.services.evaluation_worker.get_service_client", return_value=watchdog_service):
        assert run_one(
            service, worker_id="worker", heartbeat_seconds=1,
            soft_timeout_seconds=0.005, hard_timeout_seconds=0.015,
            hard_exit=exits.append,
        ) is True
    watchdog_service.rpc.assert_called_once_with(
        "timeout_evaluation_job",
        {
            "p_id": JOB, "p_worker": "worker",
            "p_reason": "Evaluation processing exceeded its safe duration.",
        },
    )
    assert exits == [70]


def test_stage2_artifact_audit_and_manual_failure_are_admin_only():
    evaluation_id = str(uuid4())
    artifact_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    service = Service({
        "tenants": [{"id": TENANT, "handwritten_evaluation_enabled": True}],
        "handwritten_evaluations": [{"id": evaluation_id, "tenant_id": TENANT}],
        "handwritten_stage2_artifacts": [{
            "id": artifact_id, "tenant_id": TENANT, "evaluation_id": evaluation_id,
            "sequence": 1, "route": "whole_paper", "model": "deepseek",
            "prompt_revision": "v2", "raw_content": "{}", "content_bytes": 2,
            "content_sha256": "a" * 64, "content_omitted": False, "created_at": now,
        }],
    })
    teacher = profile("teacher")
    with pytest.raises(HTTPException) as denied:
        asyncio.run(get_stage2_artifacts(UUID(evaluation_id), teacher))
    assert denied.value.status_code == 403

    admin = profile("institution_admin")
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service):
        result = asyncio.run(get_stage2_artifacts(UUID(evaluation_id), admin))
    assert str(result.artifacts[0].id) == artifact_id
    assert result.artifacts[0].raw_content == "{}"

    rpc = Mock()
    rpc.execute.return_value = SimpleNamespace(data=True)
    service.rpc = Mock(return_value=rpc)
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service):
        changed = asyncio.run(mark_submission_failed(
            UUID(SUBMISSION), MarkFailedRequest(reason="Operator recovery"), admin,
        ))
    assert changed == {"changed": True}
    service.rpc.assert_called_once_with("mark_handwritten_submission_failed", {
        "p_tenant": TENANT, "p_submission": SUBMISSION,
        "p_reason": "Operator recovery",
    })


class _PhaseAQuery(Query):
    def execute(self):
        if self.inserting and self.table == "evaluation_papers":
            self.payload = {
                "rubric_status": "not_started",
                "is_active": True,
                "created_at": datetime.now(UTC).isoformat(),
                **self.payload,
            }
        if self.inserting and self.table == "evaluation_upload_intents":
            self.payload = {
                "status": "pending",
                "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "verified_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                **self.payload,
            }
        return super().execute()


class _PhaseAService(Service):
    def table(self, name):
        return _PhaseAQuery(self, name)

    def rpc(self, name, params):
        service = self

        class _Call:
            def execute(self):
                if name == "create_limited_handwritten_submission_job":
                    intent = next(row for row in service.tables["evaluation_upload_intents"] if row["id"] == params["p_intent"])
                    existing = next((row for row in service.tables.setdefault("handwritten_submissions", []) if row["upload_intent_id"] == intent["id"]), None)
                    if existing is None:
                        existing = {
                            "id": str(uuid4()), "tenant_id": params["p_tenant"],
                            "student_id": params["p_student"],
                            "evaluation_paper_id": intent["evaluation_paper_id"],
                            "upload_intent_id": intent["id"], "answer_script_path": intent["storage_path"],
                            "status": "queued", "created_at": datetime.now(UTC).isoformat(),
                        }
                        service.tables["handwritten_submissions"].append(existing)
                        intent["status"] = "consumed"
                        service.tables.setdefault("evaluation_jobs", []).append({
                            "id": str(uuid4()), "tenant_id": params["p_tenant"],
                            "submission_id": existing["id"], "owner_student_id": params["p_student"],
                            "status": "queued", "attempts": 0,
                        })
                    job = next(row for row in service.tables["evaluation_jobs"] if row["submission_id"] == existing["id"])
                    return SimpleNamespace(data={"submission": deepcopy(existing), "job": deepcopy(job)})
                if name == "claim_evaluation_job":
                    job = next((row for row in service.tables["evaluation_jobs"] if row["status"] == "queued"), None)
                    if job:
                        job.update(status="claimed", claimed_by=params["p_worker"], attempts=job["attempts"] + 1)
                    return SimpleNamespace(data=deepcopy(job))
                job = next(row for row in service.tables["evaluation_jobs"] if row["id"] == params["p_id"])
                submission = next(row for row in service.tables["handwritten_submissions"] if row["id"] == job["submission_id"])
                if name == "start_evaluation_job":
                    job["status"] = "processing"; submission["status"] = "processing_stage1"
                elif name == "finish_evaluation_stub_job":
                    job["status"] = "done"; submission["status"] = "pending_stage1"
                elif name == "finish_evaluation_stage1_job":
                    job["status"] = "done"
                    submission.update(
                        status="review" if params["p_requires_review"] else "stage1_complete",
                        stage1_extraction=params["p_extraction"],
                        stage1_extraction_source=params["p_source"],
                        page_mapping=params["p_mapping"],
                    )
                elif name == "fail_evaluation_job":
                    job["status"] = "failed"; submission["status"] = "failed"
                return SimpleNamespace(data=True)

        return _Call()


def test_full_flow_runs_stage1_and_persists_extraction():
    course, level, subject = str(uuid4()), str(uuid4()), str(uuid4())
    service = _PhaseAService({
        "tenants": [{"id": TENANT, "is_active": True, "handwritten_evaluation_enabled": True}],
        "profiles": [
            {"id": TEACHER, "tenant_id": TENANT, "role": "teacher"},
            {"id": STUDENT, "tenant_id": TENANT, "role": "student"},
        ],
        "teacher_subjects": [{"tenant_id": TENANT, "teacher_id": TEACHER, "subject_id": subject}],
        "subjects": [{"id": subject, "tenant_id": TENANT, "course_id": course, "course_level_id": level}],
        "enrollments": [{"tenant_id": TENANT, "profile_id": STUDENT, "course_id": course, "course_level_id": level}],
    })
    upload = UploadFile(
        filename="mock.pdf",
        file=io.BytesIO(b"%PDF-1.7\nquestion"),
        headers=Headers({"content-type": "application/pdf"}),
    )
    with patch("app.api.evaluation_papers.get_service_client", return_value=service), \
         patch("app.api.evaluation_papers.upload_bytes"), \
         patch("app.api.evaluation_papers.signed_url", return_value="https://signed.example/paper"):
        paper = asyncio.run(create_evaluation_paper(
            course_level_id=UUID(level), subject_id=UUID(subject), title="Mock exam",
            total_marks=100, generated_paper_id=None, question_paper=upload,
            suggested_answer=None, profile=profile("teacher"),
        ))

    answer = b"%PDF-1.7\ncompleted answers"
    intent_body = UploadIntentRequest(
        paper_id=paper.id, filename="answers.pdf", content_type="application/pdf", size_bytes=len(answer)
    )
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.signed_upload", return_value={"signed_url": "https://signed.example/upload", "token": "token"}):
        intent = asyncio.run(create_upload_intent(intent_body, profile()))
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch("app.api.handwritten_submissions.download_bytes", return_value=answer):
        assert asyncio.run(finalize_upload_intent(intent.id, profile())).status == "verified"
    with patch("app.api.handwritten_submissions.get_service_client", return_value=service), \
         patch(
             "app.api.handwritten_submissions.get_settings",
             return_value=SimpleNamespace(
                 evaluation_jobs_enabled=True,
                 handwritten_evaluation_attempts_per_paper=2,
             ),
         ):
        submission = asyncio.run(create_submission(CreateSubmissionRequest(upload_intent_id=intent.id), profile()))
    stage1_payload = {"text_answers": [], "tables": [], "numerical_workings": [],
                      "page_manifest": [], "legibility_report": {"overall_legibility": "clear"}}
    outcome = Stage1Outcome(stage1_payload, f"{TENANT}/{STUDENT}/{intent.id}/answers.pdf", {}, False)
    with patch("app.services.evaluation_worker.get_service_client", return_value=service), \
         patch("app.services.evaluation_worker.run_stage1", return_value=outcome):
        assert run_one(worker_id="phase-a-worker") is True
    stored = next(row for row in service.tables["handwritten_submissions"] if row["id"] == str(submission.id))
    assert stored["status"] == "stage1_complete"
    assert stored["stage1_extraction"] == stage1_payload
    assert service.tables["evaluation_jobs"][0]["status"] == "done"
