from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.questions import QuestionEdit, edit_question
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
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, values: dict):
        self.updates = values
        return self

    def execute(self):
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
