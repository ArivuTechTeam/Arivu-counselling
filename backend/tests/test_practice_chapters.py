from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.practice import StartPractice, practice_subject_chapters, preview_practice, start_practice
from app.lib.auth import CurrentProfile


def _profile(role: str = "student") -> CurrentProfile:
    return CurrentProfile(user_id="student-a", tenant_id="tenant-a", role=role)


def test_practice_chapters_are_scoped_to_enrolled_subject_and_tenant() -> None:
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": "chapter-a", "name": "Basics"}])
    service = MagicMock()
    service.table.return_value = query

    with patch("app.api.practice.get_service_client", return_value=service), patch(
        "app.api.practice.enrolled_subject_ids", return_value={"subject-a"}
    ):
        assert practice_subject_chapters("subject-a", _profile()) == [
            {"id": "chapter-a", "name": "Basics"}
        ]

    service.table.assert_called_once_with("chapters")
    query.eq.assert_any_call("tenant_id", "tenant-a")
    query.eq.assert_any_call("subject_id", "subject-a")


def test_practice_chapters_reject_unenrolled_subject() -> None:
    service = MagicMock()
    with patch("app.api.practice.get_service_client", return_value=service), patch(
        "app.api.practice.enrolled_subject_ids", return_value={"subject-a"}
    ):
        with pytest.raises(HTTPException) as error:
            practice_subject_chapters("subject-b", _profile())

    assert error.value.status_code == 404
    service.table.assert_not_called()


def test_practice_chapters_reject_non_students() -> None:
    with pytest.raises(HTTPException) as error:
        practice_subject_chapters("subject-a", _profile("teacher"))
    assert error.value.status_code == 403


@pytest.mark.parametrize("handler", [preview_practice, start_practice])
def test_no_matching_questions_has_actionable_public_error(handler) -> None:
    body = StartPractice(mode="smart", count=15, difficulty="medium")
    with patch("app.api.practice.get_service_client", return_value=MagicMock()), patch(
        "app.api.practice.select_question_ids", return_value=[]
    ):
        with pytest.raises(HTTPException) as error:
            handler(body, _profile())

    assert error.value.status_code == 400
    assert error.value.headers == {"X-Error-Code": "no_questions_available"}
    assert "another subject, chapter, or difficulty" in error.value.detail
