from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.quiz_persistence import (
    MAX_PERSISTED_QUESTIONS,
    QuizPersistenceError,
    persist_generated_quiz,
)


def test_atomic_persistence_uses_one_bounded_rpc_round_trip() -> None:
    service = Mock()
    service.rpc.return_value.execute.return_value = SimpleNamespace(
        data={"quiz_set_id": "quiz-1", "questions": [{"id": "question-1"}]}
    )
    payload = {"questions": [{"question_text": "Question"}]}

    result = persist_generated_quiz(
        service,
        tenant_id="tenant-1",
        actor_id="teacher-1",
        payload=payload,
    )

    assert result["quiz_set_id"] == "quiz-1"
    service.rpc.assert_called_once_with(
        "persist_generated_quiz",
        {
            "p_tenant": "tenant-1",
            "p_actor": "teacher-1",
            "p_payload": payload,
        },
    )
    service.rpc.return_value.execute.assert_called_once_with()


@pytest.mark.parametrize("questions", [[], [{}] * (MAX_PERSISTED_QUESTIONS + 1)])
def test_atomic_persistence_rejects_unbounded_payload_before_database_call(
    questions: list[dict],
) -> None:
    service = Mock()
    with pytest.raises(QuizPersistenceError):
        persist_generated_quiz(
            service,
            tenant_id="tenant-1",
            actor_id="teacher-1",
            payload={"questions": questions},
        )
    service.rpc.assert_not_called()


def test_atomic_persistence_requires_database_commit_receipt() -> None:
    service = Mock()
    service.rpc.return_value.execute.return_value = SimpleNamespace(data=None)
    with pytest.raises(QuizPersistenceError):
        persist_generated_quiz(
            service,
            tenant_id="tenant-1",
            actor_id="teacher-1",
            payload={"questions": [{}]},
        )
