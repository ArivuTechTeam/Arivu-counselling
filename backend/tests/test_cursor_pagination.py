from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.student import student_attempts
from app.api.teacher import published_quiz_monitor
from app.lib.auth import CurrentProfile
from app.lib.pagination import bounded_page_size, decode_cursor, encode_cursor


TENANT = "00000000-0000-4000-8000-000000000001"
TEACHER = "00000000-0000-4000-8000-000000000002"
STUDENT = "00000000-0000-4000-8000-000000000003"
SUBJECT = "00000000-0000-4000-8000-000000000004"
ROW_IDS = [
    "00000000-0000-4000-8000-000000000010",
    "00000000-0000-4000-8000-000000000011",
    "00000000-0000-4000-8000-000000000012",
]
AT = "2026-09-25T10:00:00+00:00"


class _RpcResult:
    def __init__(self, data) -> None:
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _Service:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict):
        self.calls.append((name, params))
        return _RpcResult(self.payload)


def _profile(role: str, user_id: str) -> CurrentProfile:
    return CurrentProfile(user_id=user_id, tenant_id=TENANT, role=role)


def test_cursor_round_trip_is_opaque_and_rejects_tampering() -> None:
    cursor = encode_cursor(datetime(2026, 9, 25, 10, tzinfo=timezone.utc), ROW_IDS[0])
    position = decode_cursor(cursor)

    assert position is not None
    assert position.occurred_at == datetime(2026, 9, 25, 10, tzinfo=timezone.utc)
    assert position.row_id == ROW_IDS[0]
    assert AT not in cursor

    with pytest.raises(HTTPException) as raised:
        decode_cursor(cursor + "corrupt")
    assert raised.value.status_code == 400


@pytest.mark.parametrize("page_size", [0, 101])
def test_page_size_is_bounded(page_size: int) -> None:
    with pytest.raises(HTTPException) as raised:
        bounded_page_size(page_size)
    assert raised.value.status_code == 400


def test_teacher_monitor_returns_only_one_page_and_scoped_continuation() -> None:
    service = _Service(
        {
            "quizzes": [
                {"id": row_id, "title": f"Quiz {index}", "_cursor_at": AT}
                for index, row_id in enumerate(ROW_IDS)
            ]
        }
    )
    with patch("app.api.teacher.get_service_client", return_value=service):
        result = asyncio.run(
            published_quiz_monitor(
                _profile("teacher", TEACHER), page_size=2, subject_id=SUBJECT
            )
        )

    assert [row["id"] for row in result["quizzes"]] == ROW_IDS[:2]
    assert all("_cursor_at" not in row for row in result["quizzes"])
    assert decode_cursor(result["next_cursor"]).row_id == ROW_IDS[1]
    assert service.calls == [
        (
            "teacher_published_quiz_metrics_page",
            {
                "p_tenant": TENANT,
                "p_teacher": TEACHER,
                "p_limit": 3,
                "p_before_at": None,
                "p_before_id": None,
                "p_subject": SUBJECT,
                "p_search": None,
            },
        )
    ]


def test_student_attempt_history_sends_verified_actor_and_filters_to_rpc() -> None:
    service = _Service(
        [
            {
                "attempt_id": row_id,
                "quiz_title": "Quiz",
                "variant_id": None,
                "variant_type": "smart",
                "subject_id": SUBJECT,
                "chapter_id": None,
                "total_score": 1,
                "max_score": 2,
                "submitted_at": AT,
                "source": "practice",
                "_cursor_at": AT,
            }
            for row_id in ROW_IDS
        ]
    )
    with patch("app.api.student.get_service_client", return_value=service):
        result = student_attempts(
            _profile("student", STUDENT),
            page_size=2,
            source="practice",
            subject_id=SUBJECT,
        )

    assert [row.attempt_id for row in result.items] == ROW_IDS[:2]
    assert decode_cursor(result.next_cursor).row_id == ROW_IDS[1]
    assert service.calls[0][0] == "student_attempt_history_page"
    assert service.calls[0][1]["p_tenant"] == TENANT
    assert service.calls[0][1]["p_student"] == STUDENT
    assert service.calls[0][1]["p_subject"] == SUBJECT


def test_paginated_routes_keep_role_checks_before_database_access() -> None:
    with pytest.raises(HTTPException) as teacher_error:
        asyncio.run(published_quiz_monitor(_profile("student", STUDENT)))
    with pytest.raises(HTTPException) as student_error:
        student_attempts(_profile("teacher", TEACHER))

    assert teacher_error.value.status_code == 403
    assert student_error.value.status_code == 403
