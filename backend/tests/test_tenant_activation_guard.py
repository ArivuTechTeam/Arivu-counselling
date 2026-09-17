from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.lib.auth import CurrentUser, get_current_profile


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        return self

    def execute(self):
        rows = [
            row
            for row in self.rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        return SimpleNamespace(data=dict(rows[0]) if rows else None)


class _Service:
    def __init__(self, profile: dict, tenant: dict | None) -> None:
        self.tables = {"profiles": [profile], "tenants": [tenant] if tenant else []}
        self.table_calls: list[str] = []

    def table(self, name: str):
        self.table_calls.append(name)
        return _Query(self.tables[name])


def request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/api/v1/test", "headers": []})


class TenantActivationGuardTests(unittest.TestCase):
    def test_inactive_institution_is_blocked(self) -> None:
        service = _Service(
            {
                "id": "user-a",
                "tenant_id": "tenant-a",
                "role": "teacher",
                "full_name": "Teacher",
                "must_change_password": False,
            },
            {"id": "tenant-a", "is_active": False},
        )
        with patch("app.lib.auth.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as caught:
                get_current_profile(request(), CurrentUser(user_id="user-a"))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("inactive", caught.exception.detail.lower())

    def test_active_institution_is_allowed(self) -> None:
        service = _Service(
            {
                "id": "user-a",
                "tenant_id": "tenant-a",
                "role": "institution_admin",
                "full_name": "Admin",
                "must_change_password": False,
            },
            {"id": "tenant-a", "is_active": True},
        )
        with patch("app.lib.auth.get_service_client", return_value=service):
            profile = get_current_profile(request(), CurrentUser(user_id="user-a"))
        self.assertEqual(profile.tenant_id, "tenant-a")

    def test_super_admin_can_reactivate_an_institution(self) -> None:
        service = _Service(
            {
                "id": "super-a",
                "tenant_id": "platform",
                "role": "super_admin",
                "full_name": "Platform Admin",
                "must_change_password": False,
            },
            None,
        )
        with patch("app.lib.auth.get_service_client", return_value=service):
            profile = get_current_profile(request(), CurrentUser(user_id="super-a"))
        self.assertEqual(profile.role, "super_admin")
        self.assertEqual(service.table_calls, ["profiles"])


if __name__ == "__main__":
    unittest.main()
