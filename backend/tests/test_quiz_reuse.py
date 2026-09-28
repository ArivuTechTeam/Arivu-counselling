from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.quiz import CopyQuizRequest, PublishQuizRequest, duplicate_quiz_set, get_quiz_set, publish_quiz_set, publish_quiz_set_to_batches
from app.api.questions import QuestionEdit, edit_question, _assert_teacher_question
from app.lib.auth import CurrentProfile
from app.services.quiz_reuse import rpc
from tests.test_question_edit_validation import _Service


PROFILE = CurrentProfile(user_id="teacher-1", tenant_id="tenant-1", role="teacher")


def test_duplicate_disabled_does_not_write():
    with patch("app.services.quiz_reuse.enabled", return_value=False), patch("app.api.quiz.get_service_client") as client:
        with pytest.raises(HTTPException) as error:
            duplicate_quiz_set(uuid4(), CopyQuizRequest(request_key=uuid4(), title="Copy"), PROFILE)
    assert error.value.status_code == 503
    client.assert_not_called()


def test_duplicate_passes_only_authenticated_ownership_to_atomic_rpc():
    service = Mock()
    service.rpc.return_value.execute.return_value.data = {"quiz_set_id": "copy"}
    quiz, key = uuid4(), uuid4()
    with patch("app.services.quiz_reuse.enabled", return_value=True), patch("app.api.quiz.get_service_client", return_value=service):
        assert duplicate_quiz_set(quiz, CopyQuizRequest(request_key=key, title=" Copy "), PROFILE) == {"quiz_set_id": "copy"}
    service.rpc.assert_called_once_with("copy_quiz_draft", {"p_id": str(quiz), "p_tenant": PROFILE.tenant_id,
        "p_actor": PROFILE.user_id, "p_key": str(key), "p_title": "Copy"})


def test_student_cannot_duplicate():
    with pytest.raises(HTTPException) as error:
        duplicate_quiz_set(uuid4(), CopyQuizRequest(request_key=uuid4(), title="Copy"),
                           CurrentProfile(user_id="student", tenant_id="tenant", role="student"))
    assert error.value.status_code == 403


def test_loading_a_changing_paper_does_not_return_a_fresh_token_for_stale_content():
    with patch("app.services.quiz_reuse.enabled", return_value=True), patch("app.api.quiz.get_service_client"), \
         patch("app.api.quiz._teacher_quiz_set"), patch("app.api.quiz.get_quiz_set_detail", return_value={"variants": []}), \
         patch("app.services.quiz_reuse.rpc", side_effect=[{"publication_token": "old"}, {"publication_token": "new"}]):
        with pytest.raises(HTTPException) as error:
            get_quiz_set("quiz", PROFILE)
    assert error.value.status_code == 409


def test_publication_requires_loaded_revision():
    with patch("app.services.quiz_reuse.enabled", return_value=True), patch("app.api.quiz.get_service_client"), \
         patch("app.api.quiz._teacher_quiz_set"):
        with pytest.raises(HTTPException) as error:
            publish_quiz_set("quiz", PROFILE)
    assert error.value.status_code == 409


def test_batch_publication_uses_atomic_rpc_for_eligible_managed_batch():
    batch = uuid4()
    profile = PROFILE.model_copy(update={"tenant_feature_flags": {"batches": True}})
    with patch("app.services.quiz_reuse.enabled", return_value=True), \
         patch("app.api.quiz.get_service_client"), \
         patch("app.api.quiz._teacher_quiz_set", return_value={"id": "quiz", "subject_id": "subject"}), \
         patch("app.api.quiz._quiz_academic_scope", return_value=("course", "level")), \
         patch("app.api.quiz._managed_batch_ids", return_value={str(batch)}), \
         patch("app.api.quiz._require_batches_enabled"), \
         patch("app.api.quiz.select_all_in", return_value=[{"id": str(batch)}]), \
         patch("app.api.quiz.get_quiz_set_detail", return_value={"variants": []}), \
         patch("app.services.quiz_reuse.rpc", return_value={"id": "quiz", "status": "published"}) as atomic, \
         patch("app.api.quiz.snapshot_published_pyq"):
        result = publish_quiz_set("quiz", profile, PublishQuizRequest(publication_token="token", batch_ids=[batch]))
    assert result["status"] == "published"
    assert atomic.call_args.args[1] == "publish_quiz_to_batches_atomic"
    assert atomic.call_args.kwargs["p_batch_ids"] == [str(batch)]
    assert atomic.call_args.kwargs["p_require_managed"] is True


def test_rejected_purge_is_part_of_the_atomic_publication_rpc() -> None:
    with patch("app.services.quiz_reuse.enabled", return_value=True), \
         patch("app.api.quiz.get_service_client"), \
         patch("app.api.quiz._teacher_quiz_set"), \
         patch("app.api.quiz.get_quiz_set_detail", return_value={"variants": []}), \
         patch("app.api.quiz.get_settings", return_value=Mock(rejected_purge_enabled=True)), \
         patch("app.services.quiz_reuse.rpc", return_value={
             "id": "quiz", "status": "published", "purged_rejected": 2,
         }) as atomic, \
         patch("app.api.quiz.purge_rejected_for_quiz_set") as post_publish_purge, \
         patch("app.api.quiz.snapshot_published_pyq"):
        result = publish_quiz_set(
            "quiz", PROFILE, PublishQuizRequest(publication_token="token")
        )
    assert result["purged_rejected"] == 2
    assert atomic.call_args.args[1] == "publish_quiz_with_rejected_purge_atomic"
    post_publish_purge.assert_not_called()


def test_batch_publication_route_requires_a_batch_before_database_access():
    with patch("app.api.quiz.get_service_client") as client:
        with pytest.raises(HTTPException) as error:
            publish_quiz_set_to_batches("quiz", PublishQuizRequest(publication_token="token", batch_ids=[]), PROFILE)
    assert error.value.status_code == 400
    client.assert_not_called()


def test_batch_publication_rejects_unmanaged_batch_before_rpc():
    batch = uuid4()
    profile = PROFILE.model_copy(update={"tenant_feature_flags": {"batches": True}})
    with patch("app.services.quiz_reuse.enabled", return_value=True), \
         patch("app.api.quiz.get_service_client"), \
         patch("app.api.quiz._teacher_quiz_set", return_value={"id": "quiz", "subject_id": "subject"}), \
         patch("app.api.quiz._quiz_academic_scope", return_value=("course", "level")), \
         patch("app.api.quiz._managed_batch_ids", return_value=set()), \
         patch("app.api.quiz._require_batches_enabled"), \
         patch("app.services.quiz_reuse.rpc") as atomic:
        with pytest.raises(HTTPException) as error:
            publish_quiz_set("quiz", profile, PublishQuizRequest(publication_token="token", batch_ids=[batch]))
    assert error.value.status_code == 403
    atomic.assert_not_called()


def test_batch_publication_rejects_student_before_database_access():
    with patch("app.api.quiz.get_service_client") as client:
        with pytest.raises(HTTPException) as error:
            publish_quiz_set("quiz", CurrentProfile(user_id="student", tenant_id="tenant", role="student"),
                             PublishQuizRequest(publication_token="token", batch_ids=[uuid4()]))
    assert error.value.status_code == 403
    client.assert_not_called()


def test_batch_publication_rejects_quiz_outside_teacher_tenant():
    service = Mock()
    service.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
    with patch("app.api.quiz.get_service_client", return_value=service), \
         patch("app.services.quiz_reuse.rpc") as atomic:
        with pytest.raises(HTTPException) as error:
            publish_quiz_set("another-tenant-quiz", PROFILE,
                             PublishQuizRequest(publication_token="token", batch_ids=[uuid4()]))
    assert error.value.status_code == 404
    atomic.assert_not_called()


def test_rpc_does_not_disclose_database_error():
    service = Mock()
    service.rpc.side_effect = RuntimeError("private data")
    with pytest.raises(HTTPException) as error:
        rpc(service, "copy_quiz_draft", PROFILE, "quiz")
    assert error.value.status_code == 503
    assert "private data" not in error.value.detail


@pytest.mark.parametrize("locked,expected", [(True, 3), (False, 2), (False, None)])
def test_edit_rejects_released_or_stale_content(locked, expected):
    service = _Service()
    row = service.rows[0]
    row.update(content_version=3, release_locked=locked)
    owner = CurrentProfile(user_id=row["created_by"], tenant_id=row["tenant_id"], role="teacher")
    before = dict(row)
    with patch("app.services.quiz_reuse.enabled", return_value=True), patch("app.api.questions.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as error:
            edit_question(row["id"], QuestionEdit(question_text="Changed", expected_version=expected), owner)
    assert error.value.status_code == 409
    assert row == before


def test_released_question_still_allows_read_only_teacher_access():
    service = _Service()
    row = service.rows[0]
    row["release_locked"] = True
    owner = CurrentProfile(user_id=row["created_by"], tenant_id=row["tenant_id"], role="teacher")
    with patch("app.services.quiz_reuse.enabled", return_value=True):
        _assert_teacher_question(service, row["id"], owner, editing=False)
        with pytest.raises(HTTPException):
            _assert_teacher_question(service, row["id"], owner)
