from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.faculty_jobs import router, list_jobs
from app.lib.auth import CurrentProfile, get_current_profile
from app.services.blueprint import BPQuestion, BPQuiz, generate_and_persist_from_material
from app.services.faculty_jobs import enqueue, load_owned, public_job
from app.services.faculty_worker import LeaseLost, process_job, run_one
from app.services.llm import LLMError
from tests.test_faculty_pilot_safety import Service


PROFILE = CurrentProfile(user_id=str(uuid4()), tenant_id=str(uuid4()), role="teacher")
SETTINGS = SimpleNamespace(faculty_jobs_enabled=True, rate_limit_blueprint_per_hour=10,
                           rate_limit_quiz_extraction_per_hour=10)


def job(**changes):
    return {"id": str(uuid4()), "tenant_id": PROFILE.tenant_id, "created_by": PROFILE.user_id,
            "lease_token": str(uuid4()), "kind": "extraction", "status": "running",
            "request": {"document_id": str(uuid4()), "subject_id": str(uuid4()), "chapter_id": str(uuid4())},
            **changes}


def authorized_service():
    service = Service({"profiles": [{"id": PROFILE.user_id, "tenant_id": PROFILE.tenant_id, "role": "teacher"}],
                       "tenants": [{"id": PROFILE.tenant_id, "is_active": True}]})
    service.rpc = Mock(return_value=Mock(execute=Mock(return_value=SimpleNamespace(data=True))))
    return service


def test_public_status_does_not_expose_worker_token_request_or_source_content():
    visible = public_job(job(checkpoint={"source": "private"}, result={"quiz_set_id": "quiz", "questions": ["private"]}))
    assert "lease_token" not in visible and "request" not in visible and "checkpoint" not in visible
    assert visible["result"] == {"quiz_set_id": "quiz"}


def test_recent_tasks_include_owned_quiz_publication_status():
    service = Mock()
    service.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        job(status="completed", result={"quiz_set_id": "quiz", "private": "never send"})
    ]
    with patch("app.api.faculty_jobs.get_settings", return_value=SETTINGS), \
         patch("app.api.faculty_jobs.get_service_client", return_value=service), \
         patch("app.api.faculty_jobs.select_all_in", return_value=[{"id": "quiz", "status": "published"}]) as select_quizzes:
        response = list_jobs(PROFILE)
    assert response["jobs"][0]["result"] == {"quiz_set_id": "quiz", "quiz_status": "published"}
    assert select_quizzes.call_args.kwargs["values"] == ["quiz"]


def test_same_import_intent_hash_ignores_temporary_upload_row_id():
    service = Mock()
    service.rpc.return_value.execute.return_value.data = job()
    request = {"document_id": "first", "subject_id": "subject", "chapter_id": "chapter", "content_hash": "bytes"}
    with patch("app.services.faculty_jobs.get_settings", return_value=SETTINGS), \
         patch("app.services.faculty_jobs.get_service_client", return_value=service), \
         patch("app.services.faculty_jobs.validate_source"):
        key = str(uuid4())
        enqueue(PROFILE, key, "extraction", request)
        first_hash = service.rpc.call_args.args[1]["p_hash"]
        enqueue(PROFILE, key, "extraction", {**request, "document_id": "second"})
        assert service.rpc.call_args.args[1]["p_hash"] == first_hash
        enqueue(PROFILE, key, "extraction", {**request, "content_hash": "different"})
        assert service.rpc.call_args.args[1]["p_hash"] != first_hash


@pytest.mark.parametrize("response,status", [({"conflict": True},409), ({"rate_limited": True,"retry_after_seconds":90},429)])
def test_queue_rejection_is_returned_without_synchronous_generation(response,status):
    service = Mock()
    service.rpc.return_value.execute.return_value.data = response
    with patch("app.services.faculty_jobs.get_settings", return_value=SETTINGS), \
         patch("app.services.faculty_jobs.get_service_client", return_value=service), \
         patch("app.services.faculty_jobs.validate_source"):
        with pytest.raises(HTTPException) as error:
            enqueue(PROFILE, str(uuid4()), "blueprint", {})
    assert error.value.status_code == status


def test_job_lookup_enforces_owner_and_tenant():
    row = job()
    service = Service({"faculty_jobs": [row]})
    with patch("app.services.faculty_jobs.get_service_client", return_value=service):
        assert load_owned(row["id"], PROFILE)["id"] == row["id"]
        for other in [PROFILE.model_copy(update={"user_id": str(uuid4())}), PROFILE.model_copy(update={"tenant_id": str(uuid4())})]:
            with pytest.raises(HTTPException) as error:
                load_owned(row["id"], other)
            assert error.value.status_code == 404


def test_disabled_queue_does_not_query_missing_table_and_rejects_students():
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_current_profile] = lambda: PROFILE
    with TestClient(app) as client, patch("app.api.faculty_jobs.get_settings", return_value=SimpleNamespace(faculty_jobs_enabled=False)), \
         patch("app.api.faculty_jobs.get_service_client") as client_factory:
        assert client.get("/api/v1/faculty-jobs").json() == {"enabled": False, "jobs": []}
        client_factory.assert_not_called()
        app.dependency_overrides[get_current_profile] = lambda: PROFILE.model_copy(update={"role": "student"})
        assert client.get("/api/v1/faculty-jobs").status_code == 403


def test_crash_after_checkpoint_resumes_without_another_model_call():
    service = authorized_service()
    row = job(checkpoint={"questions": ["already prepared"]})
    with patch("app.services.faculty_worker.validate_source"), patch("app.services.faculty_worker.prepare_extraction") as prepare:
        process_job(service, row)
    prepare.assert_not_called()
    assert service.rpc.call_args.args[0] == "finish_faculty_job"


def test_cancelled_worker_cannot_commit_prepared_output():
    service = authorized_service()
    service.rpc.return_value.execute.return_value.data = False
    with patch("app.services.faculty_worker.validate_source"), \
         patch("app.services.faculty_worker.prepare_extraction", return_value={"questions": []}):
        with pytest.raises(LeaseLost):
            process_job(service, job())
    assert all(call.args[0] != "finish_faculty_job" for call in service.rpc.call_args_list)


def test_revoked_teacher_stops_before_provider_access():
    service = authorized_service()
    service.tables["profiles"][0]["role"] = "student"
    with patch("app.services.faculty_worker.prepare_extraction") as prepare:
        with pytest.raises(ValueError):
            process_job(service, job())
    prepare.assert_not_called()


def test_worker_records_bounded_retry_request_after_provider_failure():
    row = job()
    service = Mock()
    service.rpc.return_value.execute.return_value.data = row
    with patch("app.services.faculty_worker.process_job", side_effect=LLMError("provider unavailable")):
        assert run_one(service)
    assert service.rpc.call_args.args[0] == "update_faculty_job"
    assert service.rpc.call_args.args[1]["p_retryable"] is True


def test_worker_cancels_claimed_job_when_tenant_feature_was_disabled():
    row = job()
    service = Mock()
    service.rpc.return_value.execute.return_value.data = row
    with patch(
        "app.services.faculty_worker.tenant_feature_enabled", return_value=False
    ), patch("app.services.faculty_worker.process_job") as process:
        assert run_one(service)
    process.assert_not_called()
    assert service.rpc.call_args.args[0] == "update_faculty_job"
    assert service.rpc.call_args.args[1]["p_action"] == "cancel"


def test_blueprint_prepares_atomic_payload_without_legacy_database_writes():
    service = Mock()
    service.table.side_effect = AssertionError("No result rows before atomic commit")
    question = BPQuestion(type="mcq_single", question_text="What is equity?",
                          options=[{"id":"A","text":"60"},{"id":"B","text":"140"}], correct_answer="A")
    persist = Mock(return_value={"quiz_set_id":"atomic-result"})
    with patch("app.services.blueprint._generate_with_exact_mix", return_value=(BPQuiz(questions=[question]),"fixture")), \
         patch("app.services.blueprint.verify_generated_questions", return_value=[SimpleNamespace(status="verified",warnings=[])]):
        result = generate_and_persist_from_material(service=service,tenant_id=PROFILE.tenant_id,
            material="Assets less liabilities equal equity.",subject_id="s1",chapter_name="Accounts",
            selected_topics=[],total_questions=1,question_types=["mcq_single"],type_counts={"mcq_single":1},
            cognitive_level="mixed",difficulty="easy",profile=PROFILE,persist_result=persist)
    assert result == {"quiz_set_id":"atomic-result"}
    assert persist.call_args.args[0]["questions"][0]["verification_status"] == "verified"
    service.table.assert_not_called()
