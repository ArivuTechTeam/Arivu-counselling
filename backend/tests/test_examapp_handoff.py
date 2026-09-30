from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import jwt
from fastapi.testclient import TestClient

from app.api import handoff
from app.lib.auth import CurrentProfile, get_current_profile
from app.main import app


SECRET = "examapp-test-secret-that-is-longer-than-32-bytes"
TENANT_ID = "10000000-0000-4000-8000-000000000001"
USER_ID = "20000000-0000-4000-8000-000000000002"
COURSE_ID = "30000000-0000-4000-8000-000000000003"
LEVEL_ID = "40000000-0000-4000-8000-000000000004"
CATALOG_COURSE_ID = "50000000-0000-4000-8000-000000000005"
CATALOG_LEVEL_ID = "60000000-0000-4000-8000-000000000006"


class _Query:
    def __init__(self, service: "_Service", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.inserted: dict | None = None
        self.single = False

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def insert(self, values: dict):
        self.inserted = dict(values)
        return self

    def execute(self):
        if self.inserted is not None:
            self.service.tables.setdefault(self.table, []).append(self.inserted)
            return SimpleNamespace(data=[dict(self.inserted)])
        rows = [
            dict(row)
            for row in self.service.tables.get(self.table, [])
            if all(row.get(column) == value for column, value in self.filters)
        ]
        return SimpleNamespace(data=(rows[0] if rows else None) if self.single else rows)


class _Service:
    def __init__(self, *, enabled: bool) -> None:
        self.tables = {
            "tenants": [
                {
                    "id": TENANT_ID,
                    "name": "Server-side Institution",
                    "handwritten_evaluation_enabled": enabled,
                }
            ],
            "events": [],
        }

    def table(self, name: str):
        return _Query(self, name)


def _service_with_student_course(*, linked: bool) -> _Service:
    service = _Service(enabled=True)
    service.tables.update(
        {
            "enrollments": [
                {
                    "tenant_id": TENANT_ID,
                    "profile_id": USER_ID,
                    "course_id": COURSE_ID,
                    "course_level_id": LEVEL_ID,
                }
            ],
            "courses": [
                {
                    "id": COURSE_ID,
                    "tenant_id": TENANT_ID,
                    "catalog_course_id": CATALOG_COURSE_ID if linked else None,
                }
            ],
            "course_levels": [
                {
                    "id": LEVEL_ID,
                    "tenant_id": TENANT_ID,
                    "course_id": COURSE_ID,
                    "catalog_level_id": CATALOG_LEVEL_ID if linked else None,
                }
            ],
            "catalog_courses": [
                {"id": CATALOG_COURSE_ID, "code": "CA-FND"}
            ],
            "catalog_course_levels": [
                {
                    "id": CATALOG_LEVEL_ID,
                    "catalog_course_id": CATALOG_COURSE_ID,
                    "name": "Foundation",
                }
            ],
        }
    )
    return service


def _profile(role: str = "teacher") -> CurrentProfile:
    return CurrentProfile(
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        role=role,
        full_name="Authoritative Name",
        email="teacher@example.test",
        tenant_name="Server-side Institution",
    )


def _request(service: _Service, profile: CurrentProfile, body: dict | None = None):
    app.dependency_overrides[get_current_profile] = lambda: profile
    try:
        with (
            patch.object(handoff, "get_service_client", return_value=service),
            patch.object(
                handoff,
                "get_settings",
                return_value=SimpleNamespace(
                    handoff_shared_secret=SECRET,
                    examapp_frontend_url="https://examapp.example",
                ),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            return client.post(
                "/api/v1/handoff/examapp",
                json={} if body is None else body,
                headers={"X-Tenant-ID": "spoofed-tenant", "X-Role": "super_admin"},
            )
    finally:
        app.dependency_overrides.pop(get_current_profile, None)


def _decode(response) -> dict:
    redirect_url = response.json()["redirect_url"]
    token = redirect_url.split("#token=", 1)[1].split("&next=", 1)[0]
    return jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        audience="examapp",
        issuer="quiz-generator",
    )


def test_handoff_requires_authentication() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/handoff/examapp", json={})
    assert response.status_code == 401


def test_token_contract_signature_ttl_and_event_are_exact() -> None:
    service = _Service(enabled=True)
    response = _request(service, _profile(), {"next": "/papers/new?mode=handwritten"})

    assert response.status_code == 200
    assert response.json()["redirect_url"].startswith(
        "https://examapp.example/auth/handoff#token="
    )
    assert response.json()["redirect_url"].endswith(
        "&next=/papers/new%3Fmode%3Dhandwritten"
    )
    assert "?token=" not in response.json()["redirect_url"]
    claims = _decode(response)
    assert claims["exp"] - claims["iat"] == 60
    UUID(claims["jti"], version=4)
    assert set(claims) == {
        "iss",
        "aud",
        "iat",
        "exp",
        "jti",
        "sub",
        "email",
        "name",
        "role",
        "tenant_id",
        "tenant_name",
    }
    assert claims["iss"] == "quiz-generator"
    assert claims["aud"] == "examapp"
    assert claims["sub"] == USER_ID
    assert claims["email"] == "teacher@example.test"
    assert claims["name"] == "Authoritative Name"
    assert claims["role"] == "teacher"
    assert claims["tenant_id"] == TENANT_ID
    assert claims["tenant_name"] == "Server-side Institution"
    assert len(service.tables["events"]) == 1
    event = service.tables["events"][0]
    assert event["actor_id"] == USER_ID
    assert event["tenant_id"] == TENANT_ID
    assert event["metadata"] == {"next": "/papers/new?mode=handwritten"}
    assert "token" not in event
    assert "redirect_url" not in event


def test_flag_off_is_rejected_without_using_general_feature_flags() -> None:
    service = _Service(enabled=False)
    with patch(
        "app.services.tenant_features.effective_feature_flags",
        side_effect=AssertionError("general flags must not be consulted"),
    ) as general_flags:
        denied = _request(service, _profile())
        service.tables["tenants"][0]["handwritten_evaluation_enabled"] = True
        allowed = _request(service, _profile())

    assert denied.status_code == 403
    assert allowed.status_code == 200
    general_flags.assert_not_called()


def test_server_profile_tenant_and_role_cannot_be_spoofed() -> None:
    service = _Service(enabled=True)
    response = _request(service, _profile(), {"next": "/"})
    assert response.status_code == 200
    claims = _decode(response)
    assert claims["tenant_id"] == TENANT_ID
    assert claims["role"] == "teacher"

    body_spoof = _request(
        service,
        _profile(),
        {"next": "/", "tenant_id": "spoofed", "role": "super_admin"},
    )
    assert body_spoof.status_code == 422


def test_super_admin_is_exempt_and_receives_null_tenant_claims() -> None:
    service = _Service(enabled=False)
    response = _request(service, _profile("super_admin"))
    assert response.status_code == 200
    claims = _decode(response)
    assert claims["role"] == "super_admin"
    assert claims["tenant_id"] is None
    assert claims["tenant_name"] is None
    assert service.tables["events"][0]["tenant_id"] == TENANT_ID


def test_catalog_linked_student_receives_exam_type_and_level_claims() -> None:
    response = _request(_service_with_student_course(linked=True), _profile("student"))

    assert response.status_code == 200
    claims = _decode(response)
    assert claims["exam_type"] == "CA-FND"
    assert claims["exam_level"] == "Foundation"


def test_freeform_student_course_omits_exam_context_claims() -> None:
    response = _request(_service_with_student_course(linked=False), _profile("student"))

    assert response.status_code == 200
    claims = _decode(response)
    assert "exam_type" not in claims
    assert "exam_level" not in claims


def test_non_student_roles_never_receive_exam_context_claims() -> None:
    for role in ("teacher", "institution_admin", "super_admin"):
        response = _request(_service_with_student_course(linked=True), _profile(role))

        assert response.status_code == 200
        claims = _decode(response)
        assert "exam_type" not in claims
        assert "exam_level" not in claims


def test_next_rejects_absolute_and_network_path_urls() -> None:
    for next_value in ("https://evil.example/path", "//evil.example/path"):
        response = _request(_Service(enabled=True), _profile(), {"next": next_value})
        assert response.status_code == 422


def test_migration_uses_a_dedicated_default_off_column() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = (root / "migrations/migration-76-examapp-handoff.sql").read_text()
    sql_without_comments = "\n".join(
        line.split("--", 1)[0] for line in migration.splitlines()
    )
    normalized = " ".join(sql_without_comments.lower().split())

    assert "handwritten_evaluation_enabled boolean not null default false" in normalized
    assert "feature_flags" not in normalized
