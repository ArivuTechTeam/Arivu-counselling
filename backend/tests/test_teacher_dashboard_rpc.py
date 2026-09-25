from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.academics import list_chapters
from app.api.teacher import class_overview, published_quiz_monitor
from app.lib.auth import CurrentProfile
from app.lib.supabase_queries import rpc_json_value


TENANT = "00000000-0000-4000-8000-000000000001"
TEACHER = "00000000-0000-4000-8000-000000000002"
SUBJECT = "00000000-0000-4000-8000-000000000003"


class _Rpc:
    def __init__(self, data) -> None:
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _Service:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict) -> _Rpc:
        self.calls.append((name, params))
        return _Rpc(self.payloads[name])

    def table(self, name: str):
        raise AssertionError(f"dashboard endpoint downloaded raw {name} rows")


def _teacher() -> CurrentProfile:
    return CurrentProfile(user_id=TEACHER, tenant_id=TENANT, role="teacher")


def test_class_overview_uses_one_tenant_actor_scoped_rpc() -> None:
    payload = {"class_accuracy": 83, "students": 12}
    service = _Service({"teacher_class_overview_metrics": payload})

    with patch("app.api.teacher.get_service_client", return_value=service):
        result = asyncio.run(class_overview(_teacher()))

    assert result == payload
    assert service.calls == [
        (
            "teacher_class_overview_metrics",
            {"p_tenant": TENANT, "p_teacher": TEACHER},
        )
    ]


def test_published_monitor_uses_one_tenant_actor_scoped_rpc() -> None:
    payload = {"quizzes": [{"id": "quiz-1"}]}
    service = _Service({"teacher_published_quiz_metrics": payload})

    with patch("app.api.teacher.get_service_client", return_value=service):
        result = asyncio.run(published_quiz_monitor(_teacher()))

    assert result == payload
    assert service.calls == [
        (
            "teacher_published_quiz_metrics",
            {"p_tenant": TENANT, "p_teacher": TEACHER},
        )
    ]


def test_chapter_metrics_repeat_actor_and_subject_scope_in_rpc() -> None:
    payload = [{"id": "chapter-1", "quiz_count": 3, "question_count": 30}]
    service = _Service({"teacher_chapter_metrics": payload})

    with (
        patch("app.api.academics.get_service_client", return_value=service),
        patch("app.api.academics._assert_teacher_subject"),
    ):
        result = list_chapters(SUBJECT, _teacher())

    assert result == payload
    assert service.calls == [
        (
            "teacher_chapter_metrics",
            {
                "p_tenant": TENANT,
                "p_teacher": TEACHER,
                "p_subject": SUBJECT,
            },
        )
    ]


@pytest.mark.parametrize("endpoint", [class_overview, published_quiz_monitor])
def test_teacher_dashboard_rpcs_keep_route_role_authorization(endpoint) -> None:
    student = CurrentProfile(user_id="student", tenant_id=TENANT, role="student")

    with pytest.raises(HTTPException) as raised:
        asyncio.run(endpoint(student))

    assert raised.value.status_code == 403


def test_rpc_json_value_accepts_direct_and_wrapped_jsonb() -> None:
    direct = _Service({"object_fn": {"count": 2}, "array_fn": [{"id": "one"}]})
    wrapped = _Service(
        {
            "object_fn": [{"object_fn": {"count": 2}}],
            "array_fn": [{"array_fn": [{"id": "one"}]}],
        }
    )

    assert rpc_json_value(direct, "object_fn", {}, dict) == {"count": 2}
    assert rpc_json_value(direct, "array_fn", {}, list) == [{"id": "one"}]
    assert rpc_json_value(wrapped, "object_fn", {}, dict) == {"count": 2}
    assert rpc_json_value(wrapped, "array_fn", {}, list) == [{"id": "one"}]


def test_rpc_json_value_rejects_an_unexpected_contract() -> None:
    service = _Service({"metrics": "not-json-container"})

    with pytest.raises(RuntimeError, match="invalid analytics payload"):
        rpc_json_value(service, "metrics", {}, dict)
