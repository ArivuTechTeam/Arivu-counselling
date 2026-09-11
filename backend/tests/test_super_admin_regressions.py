from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.admin import (
    AdminCreate,
    TenantCreate,
    _generate_temporary_password,
    _select_all,
    _set_provisioned_profile,
    create_admin,
    onboard_institution,
    platform_ai_monitoring,
    platform_overview,
    remove_admin,
)
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.start = 0
        self.end = len(rows)
        self.update_values: dict | None = None

    def select(self, _columns: str):
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


class _Service:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables
        self.queries: list[tuple[str, _Query]] = []

    def table(self, name: str):
        query = _Query(self.tables.setdefault(name, []))
        self.queries.append((name, query))
        return query


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
        user_id = f"auth-{self.service.next_id}"
        self.service.next_id += 1
        metadata = payload["user_metadata"]
        self.service.auth_users.add(user_id)
        # Simulate migration 11's synchronous Auth trigger.
        self.service.tables["profiles"].append(
            {
                "id": user_id,
                "tenant_id": metadata["tenant_id"],
                "role": "student",
                "full_name": metadata.get("full_name"),
                "must_change_password": False,
            }
        )
        return SimpleNamespace(user=SimpleNamespace(id=user_id))

    def delete_user(self, user_id: str):
        self.service.auth_users.discard(user_id)
        self.service.tables["profiles"] = [
            row for row in self.service.tables["profiles"] if row["id"] != user_id
        ]


class _ProvisionService:
    def __init__(self) -> None:
        self.next_id = 1
        self.auth_users: set[str] = set()
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

    def test_provisioned_profile_is_promoted_and_locked_in_one_update(self) -> None:
        service = _Service(
            {"profiles": [{"id": "new-admin", "tenant_id": "old", "role": "student"}]}
        )

        _set_provisioned_profile(
            service,
            user_id="new-admin",
            tenant_id="tenant-a",
            role="institution_admin",
            full_name="  Demo Admin  ",
        )

        profile_queries = [query for table, query in service.queries if table == "profiles"]
        self.assertEqual(len(profile_queries), 1)
        self.assertEqual(
            profile_queries[0].update_values,
            {
                "tenant_id": "tenant-a",
                "role": "institution_admin",
                "full_name": "Demo Admin",
                "must_change_password": True,
            },
        )

    def test_ai_monitoring_uses_current_quiz_state_for_published_count(self) -> None:
        service = _Service(
            {
                "questions": [
                    {
                        "id": "question-1",
                        "type": "mcq_single",
                        "difficulty": "medium",
                        "review_status": "approved",
                        "source": "ai_generated",
                        "created_at": "2026-09-09T10:00:00Z",
                    }
                ],
                "events": [],
                "quiz_sets": [
                    {"id": "quiz-1", "status": "published"},
                    {"id": "quiz-2", "status": "draft"},
                ],
            }
        )

        with patch("app.api.admin.get_service_client", return_value=service):
            result = platform_ai_monitoring(SUPER)

        self.assertEqual(result["published_quizzes"], 1)

    def test_platform_overview_is_super_only(self) -> None:
        admin = CurrentProfile(user_id="admin", tenant_id="tenant-a", role="institution_admin")
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(platform_overview(admin))
        self.assertEqual(caught.exception.status_code, 403)

    def test_create_and_remove_admin_keeps_auth_and_profile_in_sync(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service):
            created = create_admin(
                AdminCreate(
                    full_name="Demo Admin",
                    email="admin@example.com",
                    password=_generate_temporary_password(),
                    tenant_id="tenant-a",
                ),
                SUPER,
            )

            profile = next(row for row in service.tables["profiles"] if row["id"] == created["id"])
            self.assertEqual(profile["tenant_id"], "tenant-a")
            self.assertEqual(profile["role"], "institution_admin")
            self.assertTrue(profile["must_change_password"])

            remove_admin(created["id"], SUPER)

        self.assertNotIn(created["id"], service.auth_users)
        self.assertFalse(any(row["id"] == created["id"] for row in service.tables["profiles"]))

    def test_onboard_institution_creates_first_admin_in_new_tenant(self) -> None:
        service = _ProvisionService()
        with patch("app.api.admin.get_service_client", return_value=service):
            created = onboard_institution(
                TenantCreate(
                    name="Demo College",
                    subdomain="demo-college",
                    admin_full_name="First Admin",
                    admin_email="first@example.com",
                    admin_password=_generate_temporary_password(),
                ),
                SUPER,
            )

        self.assertEqual(created["name"], "Demo College")
        self.assertIsNotNone(created["admin"])
        profile = next(
            row for row in service.tables["profiles"] if row["id"] == created["admin"]["id"]
        )
        self.assertEqual(profile["tenant_id"], created["id"])
        self.assertEqual(profile["role"], "institution_admin")
        self.assertTrue(profile["must_change_password"])


if __name__ == "__main__":
    unittest.main()
