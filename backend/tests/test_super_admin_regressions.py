from __future__ import annotations

import asyncio
import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from supabase_auth.errors import AuthApiError

from app.api.admin import (
    AdminCreate,
    TenantCreate,
    TenantOption,
    TenantUpdate,
    TemporaryPasswordReset,
    _select_all,
    _set_provisioned_profile,
    create_admin,
    list_tenants,
    onboard_institution,
    platform_ai_monitoring,
    platform_overview,
    platform_stats,
    remove_admin,
    reset_admin_temporary_password,
    update_institution,
)
from app.lib.api_errors import auth_provisioning_error
from app.lib.auth import CurrentProfile


def temporary_password() -> str:
    return f"{uuid4().hex}Aa1!"


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.start = 0
        self.end = len(rows)
        self.update_values: dict | None = None
        self.selected_columns: str | None = None

    def select(self, columns: str):
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[object]):
        self.in_filters.append((column, set(values)))
        return self

    def order(self, _column: str, **_kwargs):
        return self

    def range(self, start: int, end: int):
        self.start, self.end = start, end
        return self

    def update(self, values: dict):
        self.update_values = values
        return self

    def execute(self):
        selected = [dict(row) for row in self.rows]
        for column, value in self.filters:
            selected = [row for row in selected if row.get(column) == value]
        for column, values in self.in_filters:
            selected = [row for row in selected if row.get(column) in values]
        if self.update_values is not None:
            for row in selected:
                row.update(self.update_values)
            return SimpleNamespace(data=selected)
        selected.sort(key=lambda row: row.get("id") or "")
        return SimpleNamespace(data=selected[self.start : self.end + 1])


class _RpcQuery:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def execute(self):
        return SimpleNamespace(data=self.payload)


class _Service:
    def __init__(
        self,
        tables: dict[str, list[dict]],
        rpc_payloads: dict[str, dict] | None = None,
    ) -> None:
        self.tables = tables
        self.rpc_payloads = rpc_payloads or {}
        self.queries: list[tuple[str, _Query]] = []

    def table(self, name: str):
        query = _Query(self.tables.setdefault(name, []))
        self.queries.append((name, query))
        return query

    def rpc(self, name: str, _params: dict):
        return _RpcQuery(self.rpc_payloads[name])


class _ProvisionQuery:
    def __init__(self, service: "_ProvisionService", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.operation = "select"
        self.values: dict | None = None
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
        self.operation, self.values = "update", values
        return self

    def insert(self, values: dict):
        self.operation, self.values = "insert", values
        return self

    def upsert(self, values: dict, *, on_conflict: str):
        self.operation, self.values = "upsert", values
        self.filters = [(on_conflict, values[on_conflict])]
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        rows = self.service.tables[self.table]
        matched = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        if self.operation == "insert":
            row = dict(self.values or {})
            row.setdefault("id", f"{self.table}-{self.service.next_id}")
            self.service.next_id += 1
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.operation == "upsert":
            if matched:
                for row in matched:
                    row.update(self.values or {})
                return SimpleNamespace(data=[dict(row) for row in matched])
            row = dict(self.values or {})
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        if self.operation == "update":
            for row in matched:
                row.update(self.values or {})
            return SimpleNamespace(data=[dict(row) for row in matched])
        if self.operation == "delete":
            for row in matched:
                rows.remove(row)
            return SimpleNamespace(data=[dict(row) for row in matched])
        data = [dict(row) for row in matched]
        return SimpleNamespace(data=(data[0] if data else None) if self.single else data)


class _ProvisionAuthAdmin:
    def __init__(self, service: "_ProvisionService") -> None:
        self.service = service

    def create_user(self, payload: dict):
        self.service.created_auth_payloads.append(payload)
        user_id = f"auth-{self.service.next_id}"
        self.service.next_id += 1
        self.service.auth_users.add(user_id)
        # Migration 40 bypasses the public-signup trigger at Auth insert time.
        # The API writes the authoritative profile afterward.
        return SimpleNamespace(user=SimpleNamespace(id=user_id))

    def delete_user(self, user_id: str):
        self.service.auth_users.discard(user_id)
        self.service.tables["profiles"] = [
            row for row in self.service.tables["profiles"] if row["id"] != user_id
        ]

    def update_user_by_id(self, user_id: str, attributes: dict):
        if user_id not in self.service.auth_users:
            raise RuntimeError("Auth user not found")
        self.service.updated_auth_payloads.append((user_id, attributes))
        return SimpleNamespace(user=SimpleNamespace(id=user_id))


class _ProvisionService:
    def __init__(self) -> None:
        self.next_id = 1
        self.auth_users: set[str] = set()
        self.created_auth_payloads: list[dict] = []
        self.updated_auth_payloads: list[tuple[str, dict]] = []
        self.tables = {
            "tenants": [{"id": "tenant-a", "name": "Existing", "subdomain": "existing", "is_active": True}],
            "profiles": [],
        }
        self.auth = SimpleNamespace(admin=_ProvisionAuthAdmin(self))

    def table(self, name: str):
        self.tables.setdefault(name, [])
        return _ProvisionQuery(self, name)


SUPER = CurrentProfile(
    user_id="super",
    tenant_id="platform-tenant",
    role="super_admin",
)


class SuperAdminRegressionTests(unittest.TestCase):
    def test_tenant_directory_selects_its_complete_response_contract(self) -> None:
        service = _Service(
            {
                "tenants": [
                    {
                        "id": "tenant-a",
                        "name": "Demo College",
                        "subdomain": "demo-college",
                    }
                ]
            }
        )

        with patch("app.api.admin.get_service_client", return_value=service):
            tenants = list_tenants(profile=SUPER)

        self.assertEqual(
            service.queries[0][1].selected_columns,
            "id, name, subdomain",
        )
        self.assertEqual(
            TenantOption.model_validate(tenants[0]).subdomain,
            "demo-college",
        )

    def test_auth_provisioning_errors_are_safe_and_actionable(self) -> None:
        cases = [
            ("email_exists", 422, 409, "already exists"),
            ("user_already_exists", 422, 409, "already exists"),
            ("weak_password", 422, 400, "Generate a new password"),
            ("email_address_invalid", 422, 400, "valid administrator email"),
            ("over_request_rate_limit", 429, 429, "Too many"),
            ("unexpected_failure", 500, 503, "account service"),
        ]
        for code, provider_status, expected_status, expected_detail in cases:
            with self.subTest(code=code):
                result = auth_provisioning_error(
                    AuthApiError("provider detail must stay private", provider_status, code),
                    operation="test provisioning",
                )
                self.assertEqual(result.status_code, expected_status)
                self.assertIn(expected_detail, result.detail)
                self.assertNotIn("provider detail", result.detail)

    def test_first_admin_password_uses_temporary_password_policy(self) -> None:
        with self.assertRaises(ValidationError):
            TenantCreate(
                name="Demo College",
                subdomain="demo-college",
                admin_full_name="First Admin",
                admin_email="first@example.com",
                admin_password="Short1A",
            )

    def test_select_all_crosses_postgrest_page_boundary_and_keeps_filters(self) -> None:
        service = _Service(
            {"events": [{"id": f"{i:04d}", "kind": i % 2} for i in range(2005)]}
        )

        rows = _select_all(
            service,
            "events",
            "id, kind",
            configure=lambda query: query.eq("kind", 1),
        )

        self.assertEqual(len(rows), 1002)
        self.assertEqual(rows[0]["id"], "0001")
        self.assertEqual(rows[-1]["id"], "2003")
        self.assertEqual(len(service.queries), 2)

    def test_provisioned_profile_is_created_without_signup_trigger(self) -> None:
        service = _ProvisionService()

        _set_provisioned_profile(
            service,
            user_id="new-admin",
            tenant_id="tenant-a",
            role="institution_admin",
            full_name="  Demo Admin  ",
        )

        self.assertEqual(
            service.tables["profiles"],
            [
                {
                    "id": "new-admin",
                    "tenant_id": "tenant-a",
                    "role": "institution_admin",
                    "full_name": "Demo Admin",
                    "must_change_password": True,
                }
            ],
        )

    def test_provisioned_profile_upsert_repairs_existing_profile(self) -> None:
        service = _ProvisionService()
        service.tables["profiles"].append(
            {"id": "new-admin", "tenant_id": "old", "role": "student"}
        )

        _set_provisioned_profile(
            service,
            user_id="new-admin",
            tenant_id="tenant-a",
            role="institution_admin",
            full_name="  Demo Admin  ",
        )

        self.assertEqual(
            service.tables["profiles"][0],
            {
                "id": "new-admin",
                "tenant_id": "tenant-a",
                "role": "institution_admin",
                "full_name": "Demo Admin",
                "must_change_password": True,
            },
        )

    def test_ai_monitoring_uses_current_quiz_state_for_published_count(self) -> None:
        service = _Service(
            {},
            {
                "platform_ai_monitoring_metrics": {
                    "total_generated": 1,
                    "approval_rate": 100,
                    "published_quizzes": 1,
                    "failures_14d": 0,
                    "pipeline": {
                        "pending_review": 0,
                        "approved": 1,
                        "rejected": 0,
                        "needs_edit": 0,
                    },
                    "by_type": [
                        {"type": "mcq_single", "total": 1, "approved": 1, "approval": 100}
                    ],
                    "by_difficulty": {"medium": 1},
                    "difficulty_quality": [
                        {"difficulty": "medium", "total": 1, "approved": 1, "approval": 100}
                    ],
                    "volume": [],
                    "trend": {
                        "keep_rate_last7": 0,
                        "keep_rate_prev7": 0,
                        "keep_rate_delta": 0,
                        "approved_last7": 0,
                        "approved_prev7": 0,
                        "has_trend": False,
                    },
                    "funnel": [],
                    "signals": {
                        "measured_from": None,
                        "generated": 0,
                        "reviewed": 0,
                        "approved": 0,
                        "rejected": 0,
                        "kept_as_is": 0,
                        "approved_after_edit": 0,
                        "regenerated": 0,
                        "pending": 0,
                        "approval_rate": 0,
                        "kept_as_is_rate": 0,
                        "by_type": [],
                        "most_edited_fields": [],
                    },
                }
            },
        )

        with patch("app.api.admin.get_service_client", return_value=service):
            result = platform_ai_monitoring(SUPER)

        self.assertEqual(result["published_quizzes"], 1)

    def test_super_admin_can_update_safe_tenant_lifecycle_fields(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service):
            result = update_institution(
                "tenant-a",
                TenantUpdate(
                    name="Renamed Institution",
                    subdomain="  renamed-institution  ",
                    plan_tier="growth",
                    is_active=False,
                    primary_color="#7c3aed",
                    handwritten_evaluation_enabled=True,
                ),
                SUPER,
            )

        self.assertEqual(result["name"], "Renamed Institution")
        self.assertEqual(result["subdomain"], "renamed-institution")
        self.assertEqual(result["plan_tier"], "growth")
        self.assertFalse(result["is_active"])
        self.assertEqual(result["primary_color"], "#7C3AED")
        self.assertTrue(result["handwritten_evaluation_enabled"])
        stored = next(row for row in service.tables["tenants"] if row["id"] == "tenant-a")
        self.assertEqual(stored["name"], "Renamed Institution")
        self.assertEqual(stored["subdomain"], "renamed-institution")
        self.assertFalse(stored["is_active"])
        self.assertEqual(stored["primary_color"], "#7C3AED")
        self.assertTrue(stored["handwritten_evaluation_enabled"])
        self.assertNotIn("handwritten_evaluation_enabled", stored.get("feature_flags", {}))

    def test_tenant_brand_color_must_be_six_digit_hex(self) -> None:
        with self.assertRaises(ValidationError):
            TenantUpdate(primary_color="green")

    def test_tenant_access_url_rejects_invalid_or_duplicate_slugs(self) -> None:
        service = _ProvisionService()
        service.tables["tenants"].append(
            {
                "id": "tenant-b",
                "name": "Other Institution",
                "subdomain": "already-used",
                "is_active": True,
            }
        )

        with patch("app.api.admin.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as invalid:
                update_institution(
                    "tenant-a",
                    TenantUpdate(subdomain="invalid--slug"),
                    SUPER,
                )
            with self.assertRaises(HTTPException) as duplicate:
                update_institution(
                    "tenant-a",
                    TenantUpdate(subdomain="already-used"),
                    SUPER,
                )

        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(duplicate.exception.status_code, 409)
        stored = next(row for row in service.tables["tenants"] if row["id"] == "tenant-a")
        self.assertEqual(stored["subdomain"], "existing")

    def test_only_super_admin_can_change_tenant_access_url(self) -> None:
        service = _ProvisionService()
        institution_admin = CurrentProfile(
            user_id="admin",
            tenant_id="tenant-a",
            role="institution_admin",
        )

        with (
            patch("app.api.admin.get_service_client", return_value=service),
            self.assertRaises(HTTPException) as caught,
        ):
            update_institution(
                "tenant-a",
                TenantUpdate(subdomain="renamed-institution"),
                institution_admin,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(service.tables["tenants"][0]["subdomain"], "existing")

    def test_replacing_tenant_logo_preserves_original_filename(self) -> None:
        service = _ProvisionService()
        png = b"\x89PNG\r\n\x1a\n" + b"safe-image"
        with (
            patch("app.api.admin.get_service_client", return_value=service),
            patch("app.api.admin.upload_bytes") as upload,
            patch("app.api.admin.signed_url", return_value="https://signed.example/logo"),
        ):
            result = update_institution(
                "tenant-a",
                TenantUpdate(
                    plan_tier="free",
                    logo_data=base64.b64encode(png).decode(),
                    logo_content_type="image/png",
                    logo_filename="alliance-mark.png",
                ),
                SUPER,
            )

        stored = next(row for row in service.tables["tenants"] if row["id"] == "tenant-a")
        self.assertEqual(stored["logo_filename"], "alliance-mark.png")
        self.assertTrue(stored["logo_url"].endswith(".png"))
        self.assertEqual(result["logo_filename"], "alliance-mark.png")
        self.assertEqual(result["logo_url"], "https://signed.example/logo")
        upload.assert_called_once()

    def test_platform_overview_is_super_only(self) -> None:
        admin = CurrentProfile(user_id="admin", tenant_id="tenant-a", role="institution_admin")
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(platform_overview(admin))
        self.assertEqual(caught.exception.status_code, 403)

    def test_platform_stats_reuses_database_aggregate(self) -> None:
        service = _Service(
            {},
            {
                "platform_overview_metrics": {
                    "institutions": 2,
                    "teachers": 5,
                    "students": 30,
                    "institutions_table": [
                        {"id": "b", "name": "Beta", "teachers": 2, "students": 10},
                        {"id": "a", "name": "Alpha", "teachers": 3, "students": 20},
                    ],
                }
            },
        )
        with patch("app.api.admin.get_service_client", return_value=service):
            result = platform_stats(SUPER)

        self.assertEqual(result["total_teachers"], 5)
        self.assertEqual(result["total_students"], 30)
        self.assertEqual(
            [tenant["name"] for tenant in result["per_institution"]],
            ["Alpha", "Beta"],
        )
        self.assertEqual(service.queries, [])

    def test_create_and_remove_admin_keeps_auth_and_profile_in_sync(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service), patch(
            "app.api.admin.erase_account_data"
        ):
            created = create_admin(
                AdminCreate(
                    full_name="Demo Admin",
                    email="admin@example.com",
                    password=temporary_password(),
                    tenant_id="tenant-a",
                ),
                SUPER,
            )

            self.assertEqual(created, {"created": True})
            created_id = next(iter(service.auth_users))
            profile = next(row for row in service.tables["profiles"] if row["id"] == created_id)
            self.assertEqual(profile["tenant_id"], "tenant-a")
            self.assertEqual(profile["role"], "institution_admin")
            self.assertTrue(profile["must_change_password"])
            payload = service.created_auth_payloads[-1]
            self.assertTrue(
                payload["user_metadata"]["_backend_provisioning_intent"]
            )
            self.assertTrue(payload["app_metadata"]["provisioned_by_backend"])

            remove_admin(created_id, SUPER)

        self.assertNotIn(created_id, service.auth_users)
        self.assertFalse(any(row["id"] == created_id for row in service.tables["profiles"]))

    def test_onboard_institution_creates_first_admin_in_new_tenant(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service):
            created = onboard_institution(
                TenantCreate(
                    name="Demo College",
                    subdomain="demo-college",
                    admin_full_name="First Admin",
                    admin_email="first@example.com",
                    admin_password=temporary_password(),
                ),
                SUPER,
            )

        self.assertTrue(created["created"])
        self.assertEqual(created["tenant_id"], "tenants-1")
        created_tenant = next(
            row for row in service.tables["tenants"] if row["subdomain"] == "demo-college"
        )
        profile = next(
            row
            for row in service.tables["profiles"]
            if row["tenant_id"] == created_tenant["id"]
        )
        self.assertEqual(profile["tenant_id"], created_tenant["id"])
        self.assertEqual(profile["role"], "institution_admin")
        self.assertTrue(profile["must_change_password"])
        payload = service.created_auth_payloads[-1]
        self.assertTrue(payload["user_metadata"]["_backend_provisioning_intent"])
        self.assertTrue(payload["app_metadata"]["provisioned_by_backend"])

    def test_onboard_institution_provisions_selected_catalog_offerings(self) -> None:
        service = _ProvisionService()
        subject_ids = [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ]
        with (
            patch("app.api.admin.get_service_client", return_value=service),
            patch(
                "app.api.admin.active_catalog_subject_ids",
                return_value=set(subject_ids),
            ),
            patch("app.api.admin.provision_catalog_subject") as provision,
        ):
            created = onboard_institution(
                TenantCreate(
                    name="Catalog College",
                    subdomain="catalog-college",
                    admin_full_name="First Admin",
                    admin_email="catalog@example.com",
                    admin_password=temporary_password(),
                    catalog_subject_ids=subject_ids,
                ),
                SUPER,
            )

        self.assertTrue(created["created"])
        self.assertEqual(provision.call_count, 2)
        self.assertEqual(
            [call.kwargs["catalog_subject_id"] for call in provision.call_args_list],
            subject_ids,
        )
        self.assertTrue(
            all(
                call.kwargs["tenant_id"] == created["tenant_id"]
                for call in provision.call_args_list
            )
        )

    def test_onboard_institution_rolls_back_when_catalog_provisioning_fails(self) -> None:
        service = _ProvisionService()
        subject_id = "11111111-1111-4111-8111-111111111111"
        with (
            patch("app.api.admin.get_service_client", return_value=service),
            patch(
                "app.api.admin.active_catalog_subject_ids",
                return_value={subject_id},
            ),
            patch(
                "app.api.admin.provision_catalog_subject",
                side_effect=RuntimeError("catalog unavailable"),
            ),
        ):
            with self.assertRaises(HTTPException) as error:
                onboard_institution(
                    TenantCreate(
                        name="Rollback College",
                        subdomain="rollback-college",
                        admin_full_name="First Admin",
                        admin_email="rollback@example.com",
                        admin_password=temporary_password(),
                        catalog_subject_ids=[subject_id],
                    ),
                    SUPER,
                )

        self.assertEqual(error.exception.status_code, 400)
        self.assertFalse(
            any(
                row["subdomain"] == "rollback-college"
                for row in service.tables["tenants"]
            )
        )
        self.assertFalse(service.auth_users)

    def test_super_admin_can_reset_institution_admin_temporary_password(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service):
            create_admin(
                AdminCreate(
                    full_name="Demo Admin",
                    email="admin@example.com",
                    password=temporary_password(),
                    tenant_id="tenant-a",
                ),
                SUPER,
            )
            created_id = next(iter(service.auth_users))
            stored_profile = next(
                row for row in service.tables["profiles"] if row["id"] == created_id
            )
            stored_profile["must_change_password"] = False
            new_password = temporary_password()

            result = reset_admin_temporary_password(
                created_id,
                TemporaryPasswordReset(password=new_password),
                SUPER,
            )

        self.assertTrue(result.changed)
        self.assertTrue(stored_profile["must_change_password"])
        self.assertEqual(
            service.updated_auth_payloads,
            [
                (
                    created_id,
                    {
                        "password": new_password,
                        "user_metadata": {"must_change_password": True},
                    },
                )
            ],
        )

    def test_institution_admin_cannot_reset_another_admin_password(self) -> None:
        institution_admin = CurrentProfile(
            user_id="admin-a",
            tenant_id="tenant-a",
            role="institution_admin",
        )
        with self.assertRaises(HTTPException) as caught:
            reset_admin_temporary_password(
                "admin-b",
                TemporaryPasswordReset(password=temporary_password()),
                institution_admin,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_super_admin_cannot_reset_non_admin_account(self) -> None:
        service = _ProvisionService()
        service.tables["profiles"].append(
            {"id": "student-a", "tenant_id": "tenant-a", "role": "student"}
        )
        with patch("app.api.admin.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as caught:
                reset_admin_temporary_password(
                    "student-a",
                    TemporaryPasswordReset(password=temporary_password()),
                    SUPER,
                )
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
