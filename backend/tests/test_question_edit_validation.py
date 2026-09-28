from __future__ import annotations

from types import SimpleNamespace
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.questions import (
    QuestionApproval,
    QuestionEdit,
    approve_question,
    edit_question,
    reject_question,
    unreject_question,
)
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, service: "_Service") -> None:
        self.service = service
        self.filters: list[tuple[str, object]] = []
        self.single = False
        self.updates: dict | None = None

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        if column in {"options", "correct_answer", "verification_warnings"} and isinstance(value, str):
            value = json.loads(value)
        self.filters.append((column, value))
        return self

    def is_(self, column: str, _value: str):
        self.filters.append((column, None))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, values: dict):
        self.updates = values
        return self

    def execute(self):
        if self.updates is not None and getattr(self.service, "before_update", None):
            hook, self.service.before_update = self.service.before_update, None
            hook()
        rows = [
            row
            for row in self.service.rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        if self.updates is not None:
            for row in rows:
                row.update(self.updates)
        data = [dict(row) for row in rows]
        return SimpleNamespace(
            data=(data[0] if data else None) if self.single else data
        )


class _Service:
    def __init__(self) -> None:
        self.rows = [
            {
                "id": "question-1",
                "tenant_id": "tenant-1",
                "created_by": "teacher-1",
                "type": "mcq_single",
                "question_text": "Choose one",
                "options": [
                    {"id": "a", "text": "Alpha"},
                    {"id": "b", "text": "Beta"},
                ],
                "correct_answer": "a",
                "explanation": None,
                "difficulty": "medium",
                "marks": 1,
                "review_status": "pending_review",
                "verification_status": "verified",
                "verification_warnings": [],
            }
        ]

    def table(self, name: str):
        assert name == "questions"
        return _Query(self)


PROFILE = CurrentProfile(
    user_id="teacher-1", tenant_id="tenant-1", role="teacher"
)


def test_text_only_edit_preserves_and_validates_existing_answer_shape() -> None:
    service = _Service()
    with patch("app.api.questions.get_service_client", return_value=service), patch(
        "app.api.questions.log_event"
    ):
        result = edit_question(
            "question-1", QuestionEdit(question_text="Updated question"), PROFILE
        )

    assert result["question_text"] == "Updated question"
    assert result["correct_answer"] == "a"
    assert result["verification_status"] == "needs_teacher_review"
    assert result["review_status"] == "pending_review"
    assert any("edited after" in warning for warning in result["verification_warnings"])


@pytest.mark.parametrize(
    "edit",
    [
        QuestionEdit(correct_answer="missing"),
        QuestionEdit(options=[{"id": "b", "text": "Beta"}]),
        QuestionEdit(correct_answer=None),
    ],
)
def test_invalid_partial_answer_edit_is_rejected_without_persisting(
    edit: QuestionEdit,
) -> None:
    service = _Service()
    original = dict(service.rows[0])
    with patch("app.api.questions.get_service_client", return_value=service), patch(
        "app.api.questions.log_event"
    ):
        with pytest.raises(HTTPException) as raised:
            edit_question("question-1", edit, PROFILE)

    assert raised.value.status_code == 400
    assert "Invalid answer configuration" in raised.value.detail
    assert service.rows[0] == original


def test_valid_options_and_answer_are_updated_together() -> None:
    service = _Service()
    options = [{"id": "c", "text": "Gamma"}, {"id": "d", "text": "Delta"}]
    with patch("app.api.questions.get_service_client", return_value=service), patch(
        "app.api.questions.log_event"
    ):
        result = edit_question(
            "question-1",
            QuestionEdit(options=options, correct_answer="d"),
            PROFILE,
        )

    assert result["options"] == options
    assert result["correct_answer"] == "d"


def test_cross_tenant_question_is_not_visible() -> None:
    service = _Service()
    other = CurrentProfile(
        user_id="teacher-1", tenant_id="tenant-2", role="teacher"
    )
    with patch("app.api.questions.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as raised:
            edit_question(
                "question-1", QuestionEdit(question_text="Not allowed"), other
            )

    assert raised.value.status_code == 404


def test_unsupported_question_can_be_approved_without_changing_ai_warning() -> None:
    service = _Service()
    service.rows[0]["verification_status"] = "unsupported"
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        result = approve_question("question-1", PROFILE)
    assert result["review_status"] == "approved"
    assert result["verification_status"] == "unsupported"


@pytest.mark.parametrize("verification", ["unsupported", "ambiguous", "needs_teacher_review", "verified"])
def test_unchanged_form_save_preserves_verification_and_review(verification: str) -> None:
    service = _Service()
    service.rows[0].update(verification_status=verification, review_status="approved",
                           reviewed_by="teacher-1", reviewed_at="2026-09-19T00:00:00Z")
    original = dict(service.rows[0])
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event") as event:
        result = edit_question("question-1", QuestionEdit(
            question_text=original["question_text"], options=original["options"],
            correct_answer=original["correct_answer"], explanation=original["explanation"],
        ), PROFILE)
    assert result == original
    assert service.rows[0] == original
    event.assert_not_called()


def test_unchanged_save_preserves_warning_but_teacher_can_approve() -> None:
    service = _Service()
    service.rows[0]["verification_status"] = "unsupported"
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        edit_question("question-1", QuestionEdit(question_text="Choose one", explanation=""), PROFILE)
        assert service.rows[0]["verification_status"] == "unsupported"
        result = approve_question("question-1", PROFILE)
    assert result["review_status"] == "approved"
    assert result["verification_status"] == "unsupported"


def test_unreject_moves_rejected_question_back_to_pending() -> None:
    service = _Service()
    service.rows[0]["review_status"] = "rejected"
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        result = unreject_question("question-1", PROFILE)
    assert result["review_status"] == "pending_review"
    assert service.rows[0]["review_status"] == "pending_review"


def test_reject_then_unreject_round_trips() -> None:
    service = _Service()
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        reject_question("question-1", PROFILE)
        assert service.rows[0]["review_status"] == "rejected"
        unreject_question("question-1", PROFILE)
    assert service.rows[0]["review_status"] == "pending_review"


@pytest.mark.parametrize("verification", [None, "unsupported", "ambiguous", "needs_teacher_review"])
def test_uncertain_item_accepts_teacher_approval_without_note(verification: str | None) -> None:
    service = _Service()
    service.rows[0]["verification_status"] = verification
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        result = approve_question("question-1", PROFILE)
    assert result["review_status"] == "approved"
    assert result["verification_status"] == verification
    assert result["reviewed_by"] == PROFILE.user_id


def test_teacher_resolution_cannot_approve_invalid_answer_shape() -> None:
    service = _Service()
    service.rows[0]["correct_answer"] = "missing-option"
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        with pytest.raises(HTTPException) as raised:
            approve_question("question-1", PROFILE, QuestionApproval(resolution_note="I checked the source and confirmed the answer."))
    assert raised.value.status_code == 409
    assert service.rows[0]["review_status"] == "pending_review"


def test_verified_item_remains_approvable_without_note() -> None:
    service = _Service()
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        assert approve_question("question-1", PROFILE)["review_status"] == "approved"


@pytest.mark.parametrize("action", ["approve", "edit"])
def test_concurrent_content_change_is_not_overwritten_or_approved(action: str) -> None:
    service = _Service()
    service.before_update = lambda: service.rows[0].update(correct_answer="b", review_status="pending_review")
    with patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event") as event:
        with pytest.raises(HTTPException) as raised:
            if action == "approve":
                approve_question("question-1", PROFILE)
            else:
                edit_question("question-1", QuestionEdit(correct_answer="a", explanation="New explanation"), PROFILE)
    assert raised.value.status_code == 409
    assert service.rows[0]["correct_answer"] == "b"
    assert service.rows[0]["review_status"] == "pending_review"
    event.assert_not_called()


def test_http_approval_accepts_resolution_body_and_returns_review_metadata() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.questions import router, get_current_profile

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_profile] = lambda: PROFILE
    service = _Service()
    service.rows[0]["verification_status"] = "unsupported"
    with TestClient(app) as client, patch("app.api.questions.get_service_client", return_value=service), patch("app.api.questions.log_event"):
        accepted = client.post("/api/v1/questions/question-1/approve")
        assert accepted.status_code == 200
        service.rows[0]["review_status"] = "pending_review"
        resolved = client.post("/api/v1/questions/question-1/approve", json={
            "resolution_note": "Confirmed option A against the original paper answer key."})
        assert resolved.status_code == 200
        assert resolved.json()["review_status"] == "approved"
        assert resolved.json()["verification_status"] == "unsupported"
        assert "original paper" in resolved.json()["verification_warnings"][-1]
