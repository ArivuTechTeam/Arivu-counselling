"""Rejected-question cleanup delegates to one transactional database RPC."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.services.rejected_purge import purge_rejected_for_quiz_set


def test_purge_uses_tenant_scoped_atomic_rpc() -> None:
    service = Mock()
    service.rpc.return_value.execute.return_value = SimpleNamespace(
        data={"purged": 2, "kept": 1}
    )

    result = purge_rejected_for_quiz_set(service, "tenant", "teacher", "quiz")

    assert result == {"purged": 2, "kept": 1}
    service.rpc.assert_called_once_with(
        "purge_rejected_quiz_questions_atomic",
        {"p_id": "quiz", "p_tenant": "tenant", "p_actor": "teacher"},
    )
    service.table.assert_not_called()


def test_purge_failure_is_safe_for_legacy_already_published_path() -> None:
    service = Mock()
    service.rpc.side_effect = RuntimeError("database unavailable")

    assert purge_rejected_for_quiz_set(service, "tenant", "teacher", "quiz") == {
        "purged": 0,
        "kept": 0,
    }


def test_unexpected_rpc_shape_is_not_reported_as_deleted() -> None:
    service = Mock()
    service.rpc.return_value.execute.return_value = SimpleNamespace(data=None)
    assert purge_rejected_for_quiz_set(service, "tenant", "teacher", "quiz") == {
        "purged": 0,
        "kept": 0,
    }
