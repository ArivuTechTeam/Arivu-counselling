from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.capacity_baseline import (
    CapacityConfigurationError,
    RouteSpec,
    Sample,
    build_report,
    load_scenario,
    percentile,
    validate_target,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_scenario_is_valid_and_read_only() -> None:
    name, routes = load_scenario(REPOSITORY_ROOT / "backend/scripts/capacity_scenario.json")

    assert name == "release-a-read-baseline"
    assert {route.role for route in routes} == {
        "public",
        "student",
        "teacher",
        "institution_admin",
        "super_admin",
    }
    assert all(route.method in {"GET", "HEAD"} for route in routes)


def test_scenario_rejects_write_methods(tmp_path: Path) -> None:
    scenario = tmp_path / "unsafe.json"
    scenario.write_text(
        json.dumps(
            {
                "version": 1,
                "name": "unsafe",
                "routes": [{"name": "submit", "method": "POST", "path": "/submit"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CapacityConfigurationError, match="writes are forbidden"):
        load_scenario(scenario)


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:8000", "http://localhost:8000/"])
def test_local_targets_are_allowed_without_remote_confirmation(base_url: str) -> None:
    assert validate_target(base_url, False, None).endswith("/")


def test_remote_target_requires_exact_staging_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://staging-api.example.test"
    with pytest.raises(CapacityConfigurationError, match="remote runs require"):
        validate_target(base_url, False, None)
    with pytest.raises(CapacityConfigurationError, match="exactly match"):
        validate_target(base_url, True, "other.example.test")

    monkeypatch.setenv("CAPACITY_PRODUCTION_HOST", "api.example.test")
    with pytest.raises(CapacityConfigurationError, match="production host"):
        validate_target("https://api.example.test", True, "api.example.test")

    assert validate_target(base_url, True, "staging-api.example.test") == base_url + "/"


def test_percentile_interpolates_and_handles_empty_samples() -> None:
    assert percentile([], 95) is None
    assert percentile([10], 95) == 10
    assert percentile([10, 20, 30, 40], 50) == 25


def test_report_has_route_percentiles_errors_and_no_sensitive_payloads() -> None:
    route = RouteSpec("student-stats", "GET", "/api/v1/student/stats", "student", 1, 500)
    samples = [
        Sample("student-stats", 200, 100, 80),
        Sample("student-stats", 200, 200, 150),
        Sample("student-stats", 503, 300, 250),
    ]

    report = build_report(
        scenario_name="test",
        base_url="https://staging-api.example.test/",
        concurrency=3,
        elapsed_seconds=1,
        samples=samples,
        routes=[route],
    )

    assert report["target_host"] == "staging-api.example.test"
    assert report["overall"]["errors"] == 1
    assert report["overall"]["latency_ms"] == {"p50": 200, "p95": 290.0, "p99": 298.0, "max": 300}
    assert report["routes"]["student-stats"]["p95_target_met"] is True
    assert report["objectives_met"] is False
    serialized = json.dumps(report)
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized


def test_sql_artifacts_keep_seed_guarded_and_report_read_only() -> None:
    seed_sql = (REPOSITORY_ROOT / "scripts/capacity-seed.sql").read_text(encoding="utf-8")
    report_sql = (REPOSITORY_ROOT / "scripts/capacity-database-report.sql").read_text(encoding="utf-8")

    assert "capacity_seed_confirmed" in seed_sql
    assert "STAGING_ONLY" in seed_sql
    assert "between 1 and 10" in seed_sql
    assert "begin transaction read only" in report_sql.lower()
