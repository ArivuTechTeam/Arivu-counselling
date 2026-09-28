from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.capacity_baseline import CapacityConfigurationError
from scripts.release_a_workflow_load import (
    Actor,
    PROFILE_USERS,
    load_actors,
    run_actor,
    run_workload,
    validate_write_target,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_release_profiles_are_fixed_at_expected_and_stress_concurrency() -> None:
    assert PROFILE_USERS == {"expected": 200, "stress": 500}


def test_remote_write_requires_production_denylist_and_exact_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAPACITY_PRODUCTION_HOST", raising=False)
    with pytest.raises(CapacityConfigurationError, match="confirm-write"):
        validate_write_target("https://staging.example.test", "staging.example.test", None)
    with pytest.raises(CapacityConfigurationError, match="CAPACITY_PRODUCTION_HOST"):
        validate_write_target("https://staging.example.test", "staging.example.test", "A7_WRITE_TEST")
    monkeypatch.setenv("CAPACITY_PRODUCTION_HOST", "api.example.test")
    with pytest.raises(CapacityConfigurationError, match="production host"):
        validate_write_target("https://api.example.test", "api.example.test", "A7_WRITE_TEST")
    assert validate_write_target(
        "https://staging.example.test", "staging.example.test", "A7_WRITE_TEST"
    ) == "https://staging.example.test/"


def test_actor_file_is_private_unique_and_large_enough(tmp_path: Path) -> None:
    token_file = tmp_path / "actors.json"
    token_file.write_text(json.dumps({"version": 1, "actors": [
        {"token": "x" * 20, "variant_id": "variant-1"},
        {"token": "y" * 20, "variant_id": "variant-2", "subject_id": "subject"},
    ]}), encoding="utf-8")
    token_file.chmod(0o600)
    with pytest.raises(CapacityConfigurationError, match="subject_id"):
        load_actors(token_file, 2)
    payload = json.loads(token_file.read_text(encoding="utf-8"))
    payload["actors"][0]["subject_id"] = "subject"
    token_file.write_text(json.dumps(payload), encoding="utf-8")
    assert len(load_actors(token_file, 2)) == 2
    with pytest.raises(CapacityConfigurationError, match="requires 3"):
        load_actors(token_file, 3)
    token_file.chmod(0o644)
    with pytest.raises(CapacityConfigurationError, match="group or others"):
        load_actors(token_file, 1)


def _successful_transport(method: str, url: str, token: str, body: dict | None, timeout: float):
    del token, timeout
    if url.endswith("/api/v1/quizzes?page_size=10"):
        return 200, {"items": []}
    if url.endswith("/api/v1/attempts"):
        assert method == "POST" and body == {"variant_id": "variant"}
        return 200, {"attempt_id": "attempt", "status": "in_progress", "questions": [{"id": "q1"}, {"id": "q2"}]}
    if url.endswith("/api/v1/practice/preview"):
        return 200, {"requested_count": 10, "question_count": 2}
    if url.endswith("/api/v1/practice/sessions"):
        return 200, {"attempt_id": "practice", "status": "in_progress", "questions": [{"id": "p1"}, {"id": "p2"}]}
    if "/api/v1/practice/sessions/" in url and url.endswith("/autosave"):
        assert body == {"answers": {"p1": None, "p2": None}}
        return 200, {"saved": True}
    if "/api/v1/practice/sessions/" in url and url.endswith("/submit"):
        return 200, {"status": "graded", "results": [{"id": "p1"}, {"id": "p2"}]}
    if "/api/v1/practice/sessions/" in url:
        return 200, {"attempt_id": "practice", "status": "graded", "results": [{"id": "p1"}, {"id": "p2"}]}
    if url.endswith("/autosave"):
        assert body == {"answers": {"q1": None, "q2": None}}
        return 200, {"saved": True}
    if url.endswith("/submit"):
        assert body == {"answers": [], "finalize_reason": "left"}
        return 200, {"status": "graded", "results": [{"id": "q1"}, {"id": "q2"}]}
    return 200, {"attempt_id": "attempt", "status": "graded", "results": [{"id": "q1"}, {"id": "q2"}]}


def test_workflow_checks_start_autosave_submit_and_graded_receipt() -> None:
    actor = Actor(token="x" * 20, variant_id="variant", subject_id="subject")
    samples, intact = run_actor(actor, "https://staging.example.test/", 1, _successful_transport)
    assert intact is True
    assert [sample.step for sample in samples] == [
        "catalogue", "attempt_start", "autosave", "submit", "graded_receipt",
        "practice_preview", "practice_start", "practice_autosave",
        "practice_submit", "practice_graded_receipt"
    ]
    report = run_workload(
        actors=[actor, Actor(token="y" * 20, variant_id="variant", subject_id="subject")],
        base_url="https://staging.example.test/",
        timeout=1,
        transport=_successful_transport,
    )
    assert report["virtual_users"] == 2
    assert report["completed_intact_workflows"] == 2
    assert report["overall"]["requests"] == 20
    assert report["workflow_integrity_met"] is True
    serialized = json.dumps(report)
    assert "xxxxxxxx" not in serialized
    assert "attempt\"" not in serialized


def test_failed_submission_is_not_reported_as_intact() -> None:
    def transport(method: str, url: str, token: str, body: dict | None, timeout: float):
        if url.endswith("/submit"):
            return 503, {}
        return _successful_transport(method, url, token, body, timeout)

    samples, intact = run_actor(
        Actor(token="x" * 20, variant_id="variant", subject_id="subject"),
        "https://staging.example.test/", 1, transport,
    )
    assert intact is False
    assert samples[-1].step == "submit"
    assert samples[-1].status == 503


def test_integrity_report_is_guarded_read_only_and_checks_corruption() -> None:
    sql = (REPOSITORY_ROOT / "scripts/a7-integrity-report.sql").read_text(encoding="utf-8").lower()
    assert "begin transaction read only" in sql
    assert "arivupro.capacity_started_at" in sql
    assert "graded_quiz_answer_count_mismatch" in sql
    assert "graded_practice_answer_count_mismatch" in sql
    assert "cross_tenant_quiz_answers" in sql
    assert "duplicate_practice_answers" in sql
    assert "expired_running_leases" in sql
    assert "insert into" not in sql
    assert "update public" not in sql
    assert "delete from" not in sql
