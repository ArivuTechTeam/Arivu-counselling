from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.questions import QuestionFigureUpdate, set_question_figure
from app.lib.auth import CurrentProfile


class Query:
    def __init__(self, service: "Service", table: str) -> None:
        self.service = service
        self.table_name = table
        self.filters: list[tuple[str, object]] = []
        self.updates: dict | None = None
        self.single = False

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
            for row in self.service.tables.get(self.table_name, [])
            if all(row.get(column) == value for column, value in self.filters)
        ]
        if self.updates is not None:
            for row in rows:
                row.update(self.updates)
        data = [dict(row) for row in rows]
        return SimpleNamespace(data=(data[0] if data else None) if self.single else data)


class Service:
    def __init__(self, *, linked: bool = True, figure_document: str = "document-1") -> None:
        self.tables = {
            "questions": [
                {
                    "id": "question-1",
                    "tenant_id": "tenant-1",
                    "created_by": "teacher-1",
                    "figure_id": None,
                }
            ],
            "quiz_variant_questions": (
                [{"question_id": "question-1", "variant_id": "variant-1", "tenant_id": "tenant-1"}]
                if linked
                else []
            ),
            "quiz_variants": [
                {"id": "variant-1", "quiz_set_id": "quiz-1", "tenant_id": "tenant-1"}
            ],
            "quiz_sets": [
                {"id": "quiz-1", "document_id": "document-1", "tenant_id": "tenant-1"}
            ],
            "document_figures": [
                {"id": "figure-1", "document_id": figure_document, "tenant_id": "tenant-1"}
            ],
        }

    def table(self, name: str):
        return Query(self, name)


TEACHER = CurrentProfile(user_id="teacher-1", tenant_id="tenant-1", role="teacher")


def test_figure_cannot_be_attached_without_a_source_document() -> None:
    service = Service(linked=False)
    with patch("app.api.questions.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as raised:
            set_question_figure("question-1", QuestionFigureUpdate(figure_id="figure-1"), TEACHER)

    assert raised.value.status_code == 400
    assert service.tables["questions"][0]["figure_id"] is None


def test_figure_must_belong_to_the_question_source_document() -> None:
    service = Service(figure_document="document-2")
    with patch("app.api.questions.get_service_client", return_value=service):
        with pytest.raises(HTTPException) as raised:
            set_question_figure("question-1", QuestionFigureUpdate(figure_id="figure-1"), TEACHER)

    assert raised.value.status_code == 400
    assert service.tables["questions"][0]["figure_id"] is None


def test_teacher_can_attach_a_figure_from_the_same_source_document() -> None:
    service = Service()
    with patch("app.api.questions.get_service_client", return_value=service), patch(
        "app.api.questions.log_event"
    ), patch(
        "app.services.document_figures.figures_for_questions",
        return_value={"figure-1": {"id": "figure-1", "image_url": "signed"}},
    ):
        result = set_question_figure(
            "question-1", QuestionFigureUpdate(figure_id="figure-1"), TEACHER
        )

    assert result["figure_id"] == "figure-1"
    assert result["figure"]["id"] == "figure-1"


def test_non_teacher_cannot_edit_question_figures() -> None:
    student = CurrentProfile(user_id="student-1", tenant_id="tenant-1", role="student")
    with pytest.raises(HTTPException) as raised:
        set_question_figure("question-1", QuestionFigureUpdate(figure_id=None), student)

    assert raised.value.status_code == 403
