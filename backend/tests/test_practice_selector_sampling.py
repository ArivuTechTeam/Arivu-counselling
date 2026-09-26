from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.lib.auth import CurrentProfile
from app.services.selector import (
    _MAX_SAMPLE_KEY,
    _sample_practice_question_ids,
    select_question_ids,
    select_question_ids_by_type,
)


class RpcService:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict):
        self.calls.append((name, params))
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            execute=lambda: SimpleNamespace(data=payload)
        )


def profile(*, features=None) -> CurrentProfile:
    return CurrentProfile(
        user_id="student-1",
        tenant_id="tenant-1",
        role="student",
        tenant_feature_flags=features,
    )


def test_sampler_sends_actor_scope_filters_and_random_seek_key() -> None:
    service = RpcService([{"question_ids": ["q-1", "q-2"], "available": 2}])
    with patch(
        "app.services.tenant_features.get_settings",
        return_value=SimpleNamespace(batches_enabled=True),
    ), patch("app.services.selector.random.randrange", return_value=12345):
        ids = select_question_ids(
            service,
            profile(features={"batches": True}),
            subject_id="subject-1",
            chapter_id="chapter-1",
            difficulty="hard",
            count=2,
        )

    assert ids == ["q-1", "q-2"]
    assert service.calls == [(
        "select_practice_question_ids_page",
        {
            "p_tenant": "tenant-1",
            "p_student": "student-1",
            "p_limit": 2,
            "p_start_key": 12345,
            "p_batches_enabled": True,
            "p_subject": "subject-1",
            "p_chapter": "chapter-1",
            "p_difficulty": "hard",
            "p_question_type": None,
        },
    )]


def test_typed_sampler_preserves_exact_requested_counts_and_caps_total() -> None:
    service = RpcService([
        {"question_ids": ["m1", "m2"], "available": 2},
        {"question_ids": [f"t{i}" for i in range(98)], "available": 98},
    ])
    with patch("app.services.selector.random.randrange", side_effect=[11, 22]), patch(
        "app.services.selector.random.shuffle"
    ):
        ids, available = select_question_ids_by_type(
            service,
            profile(features={"batches": False}),
            subject_id="subject-1",
            type_counts={"mcq_single": 2, "true_false": 150},
        )

    assert len(ids) == 100
    assert available == {"mcq_single": 2, "true_false": 98}
    assert [call[1]["p_limit"] for call in service.calls] == [2, 98]
    assert [call[1]["p_question_type"] for call in service.calls] == [
        "mcq_single",
        "true_false",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"question_ids": "q-1", "available": 1},
        {"question_ids": ["q-1"], "available": True},
        {"question_ids": ["q-1", "q-1"], "available": 2},
        {"question_ids": ["q-1", "q-2"], "available": 1},
    ],
)
def test_sampler_rejects_invalid_rpc_contract(payload) -> None:
    service = RpcService([payload])
    with pytest.raises(RuntimeError):
        _sample_practice_question_ids(
            service,
            profile(),
            count=1,
            subject_id=None,
            chapter_id=None,
            difficulty=None,
            question_type=None,
        )


def test_random_seek_uses_the_full_nonnegative_bigint_range() -> None:
    service = RpcService([{"question_ids": [], "available": 0}])
    with patch("app.services.selector.random.randrange", return_value=0) as randrange:
        _sample_practice_question_ids(
            service,
            profile(),
            count=1,
            subject_id=None,
            chapter_id=None,
            difficulty=None,
            question_type=None,
        )
    randrange.assert_called_once_with(_MAX_SAMPLE_KEY + 1)
