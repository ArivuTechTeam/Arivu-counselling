from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.student_contact import (
    ContactCreate,
    ContactReply,
    my_contacts,
    reply_to_contact,
    submit_contact,
    support_inbox,
)
from app.lib.auth import CurrentProfile
from app.main import app


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filtered = list(rows)
        self.pending_insert: dict | None = None
        self.pending_update: dict | None = None

    def select(self, _fields: str) -> "_Query":
        return self

    def eq(self, field: str, value: str) -> "_Query":
        self.filtered = [row for row in self.filtered if row.get(field) == value]
        return self

    def gte(self, field: str, value: str) -> "_Query":
        self.filtered = [row for row in self.filtered if str(row.get(field, "")) >= value]
        return self

    def order(self, _field: str, desc: bool = False) -> "_Query":
        self.filtered = sorted(self.filtered, key=lambda row: row["created_at"], reverse=desc)
        return self

    def limit(self, count: int) -> "_Query":
        self.filtered = self.filtered[:count]
        return self

    def insert(self, row: dict) -> "_Query":
        self.pending_insert = dict(row)
        return self

    def update(self, values: dict) -> "_Query":
        self.pending_update = values
        return self

    def execute(self) -> SimpleNamespace:
        if self.pending_insert is not None:
            row = {
                **self.pending_insert,
                "status": "open",
                "reply": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.rows.append(row)
            self.filtered = [row]
        if self.pending_update is not None:
            for row in self.filtered:
                row.update(self.pending_update)
        return SimpleNamespace(data=self.filtered)


class _Service:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.lock = Lock()
        self.rpc_params: list[dict] = []

    def table(self, name: str) -> _Query:
        if name != "student_contact_requests":
            raise AssertionError(name)
        return _Query(self.rows)

    def rpc(self, name: str, params: dict):
        if name != "submit_contact_request":
            raise AssertionError(name)
        self.rpc_params.append(params)
        service = self

        class _Call:
            def execute(self):
                with service.lock:
                    now = datetime.now(timezone.utc)
                    recent = [
                        row for row in service.rows
                        if row["tenant_id"] == params["p_tenant_id"]
                        and row["requester_id"] == params["p_requester_id"]
                        and datetime.fromisoformat(row["created_at"]) > now - timedelta(seconds=60)
                    ]
                    if recent:
                        return SimpleNamespace(data={"allowed": False, "retry_after_seconds": 60})
                    row = {
                        "reference": params["p_reference"],
                        "tenant_id": params["p_tenant_id"],
                        "requester_id": params["p_requester_id"],
                        "requester_role": params["p_requester_role"],
                        "kind": params["p_kind"],
                        "category": params["p_category"],
                        "routed_to": params["p_routed_to"],
                        "message": params["p_message"],
                        "rating": params["p_rating"],
                        "status": "open",
                        "reply": None,
                        "created_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    }
                    service.rows.append(row)
                    return SimpleNamespace(data={
                        "allowed": True,
                        "reference": row["reference"],
                        "routed_to": row["routed_to"],
                        "status": row["status"],
                    })

        return _Call()


def _profile(user: str, tenant: str, role: str) -> CurrentProfile:
    return CurrentProfile(user_id=user, tenant_id=tenant, role=role)


class StudentContactTests(unittest.TestCase):
    def test_contact_routes_require_authentication(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        responses = (
            client.get("/api/v1/contact/mine"),
            client.get("/api/v1/contact/inbox"),
            client.post(
                "/api/v1/contact",
                json={
                    "kind": "support",
                    "category": "general_support",
                    "message": "Please help with this account",
                },
            ),
        )
        for response in responses:
            with self.subTest(path=response.request.url.path):
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Not authenticated")

    def test_feedback_and_app_bug_route_to_platform(self) -> None:
        service = _Service()
        with patch("app.api.student_contact.get_service_client", return_value=service):
            result = submit_contact(
                ContactCreate(kind="feedback", category="feature_idea", message="Please add more reports", rating=4),
                _profile("student-a", "tenant-a", "student"),
            )
        self.assertEqual(result.routed_to, "platform")
        self.assertEqual(service.rpc_params[0]["p_requester_id"], "student-a")
        self.assertEqual(service.rpc_params[0]["p_requester_role"], "student")
        self.assertEqual(service.rpc_params[0]["p_tenant_id"], "tenant-a")
        self.assertNotIn("requester_id", result.model_dump())

    def test_academic_support_routes_to_institution(self) -> None:
        service = _Service()
        with patch("app.api.student_contact.get_service_client", return_value=service):
            result = submit_contact(
                ContactCreate(kind="support", category="quiz_issue", message="My quiz result is missing"),
                _profile("student-a", "tenant-a", "student"),
            )
        self.assertEqual(result.routed_to, "institution")

    def test_app_bug_support_routes_to_platform(self) -> None:
        service = _Service()
        with patch("app.api.student_contact.get_service_client", return_value=service):
            result = submit_contact(
                ContactCreate(kind="support", category="app_bug", message="The page does not load"),
                _profile("student-a", "tenant-a", "student"),
            )
        self.assertEqual(result.routed_to, "platform")

    def test_teacher_and_institution_admin_requests_route_to_platform(self) -> None:
        for role in ("teacher", "institution_admin"):
            service = _Service()
            with self.subTest(role=role), patch(
                "app.api.student_contact.get_service_client", return_value=service
            ):
                result = submit_contact(
                    ContactCreate(
                        kind="support",
                        category="quiz_issue",
                        message="Quiz generation needs investigation",
                    ),
                    _profile(f"{role}-a", "tenant-a", role),
                )
            self.assertEqual(result.routed_to, "platform")
            self.assertEqual(service.rpc_params[0]["p_requester_role"], role)

    def test_student_can_contact_arivupro_for_general_support(self) -> None:
        service = _Service()
        with patch("app.api.student_contact.get_service_client", return_value=service):
            result = submit_contact(
                ContactCreate(
                    kind="support",
                    category="general_support",
                    message="I need help from the ArivuPro team",
                ),
                _profile("student-a", "tenant-a", "student"),
            )
        self.assertEqual(result.routed_to, "platform")

    def test_super_admin_cannot_create_tenant_support_request(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            submit_contact(
                ContactCreate(
                    kind="support",
                    category="general_support",
                    message="This should not create a support request",
                ),
                _profile("admin-p", "platform", "super_admin"),
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_rapid_repeat_is_limited_without_storing_duplicate(self) -> None:
        service = _Service()
        payload = ContactCreate(kind="support", category="quiz_issue", message="My quiz result is missing")
        profile = _profile("student-a", "tenant-a", "student")
        with patch("app.api.student_contact.get_service_client", return_value=service):
            submit_contact(payload, profile)
            with self.assertRaises(HTTPException) as caught:
                submit_contact(payload, profile)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "60")
        self.assertEqual(len(service.rows), 1)

    def test_simultaneous_submissions_allow_only_one(self) -> None:
        service = _Service()
        payload = ContactCreate(kind="support", category="quiz_issue", message="My quiz result is missing")
        profile = _profile("student-a", "tenant-a", "student")

        def submit():
            try:
                return submit_contact(payload, profile).status
            except HTTPException as exc:
                return exc.status_code

        with patch("app.api.student_contact.get_service_client", return_value=service):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _index: submit(), range(2)))
        self.assertCountEqual(results, ["open", 429])
        self.assertEqual(len(service.rows), 1)

    def test_unavailable_atomic_submission_fails_closed(self) -> None:
        class _Unavailable(_Service):
            def rpc(self, _name, _params):
                raise RuntimeError("provider response containing user data")

        with patch("app.api.student_contact.get_service_client", return_value=_Unavailable()):
            with self.assertRaises(HTTPException) as caught:
                submit_contact(
                    ContactCreate(kind="support", category="quiz_issue", message="My quiz result is missing"),
                    _profile("student-a", "tenant-a", "student"),
                )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("provider response", caught.exception.detail)

    def test_browser_cannot_set_routing_or_requester_identity(self) -> None:
        with self.assertRaises(ValidationError):
            ContactCreate.model_validate({
                "kind": "support", "category": "quiz_issue", "message": "A missing quiz result",
                "routed_to": "platform", "requester_id": "student-b",
                "requester_role": "institution_admin",
            })
        with self.assertRaises(HTTPException):
            submit_contact(
                ContactCreate(kind="support", category="general", message="Please check my quiz"),
                _profile("student-a", "tenant-a", "student"),
            )

    def test_requester_only_sees_own_requests(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {"reference": "AAAAAAAAAAAA", "requester_id": "teacher-a", "requester_role": "teacher", "tenant_id": "tenant-a", "kind": "support", "category": "quiz_issue", "routed_to": "platform", "message": "My quiz generation is missing", "rating": None, "status": "open", "reply": None, "created_at": now, "updated_at": now},
            {"reference": "BBBBBBBBBBBB", "requester_id": "teacher-b", "requester_role": "teacher", "tenant_id": "tenant-a", "kind": "support", "category": "quiz_issue", "routed_to": "platform", "message": "Another teacher's quiz", "rating": None, "status": "open", "reply": None, "created_at": now, "updated_at": now},
        ]
        with patch("app.api.student_contact.get_service_client", return_value=_Service(rows)):
            result = my_contacts(_profile("teacher-a", "tenant-a", "teacher"))
        self.assertEqual([item.reference for item in result], ["AAAAAAAAAAAA"])

    def test_staff_inboxes_and_replies_are_destination_and_tenant_scoped(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        common = {"requester_role": "student", "kind": "support", "category": "quiz_issue", "message": "Quiz result is missing", "rating": None, "status": "open", "reply": None, "created_at": now, "updated_at": now}
        rows = [
            {**common, "reference": "AAAAAAAAAAAA", "tenant_id": "tenant-a", "routed_to": "institution"},
            {**common, "reference": "BBBBBBBBBBBB", "tenant_id": "tenant-b", "routed_to": "institution"},
            {
                **common,
                "reference": "CCCCCCCCCCCC",
                "tenant_id": "tenant-a",
                "requester_role": "teacher",
                "routed_to": "platform",
                "tenant": {"name": "Institute A"},
                "requester": {"full_name": "Faculty A"},
            },
        ]
        service = _Service(rows)
        with patch("app.api.student_contact.get_service_client", return_value=service):
            institution = _profile("admin-a", "tenant-a", "institution_admin")
            self.assertEqual([item.reference for item in support_inbox(institution)], ["AAAAAAAAAAAA"])
            platform_items = support_inbox(_profile("admin-p", "platform", "super_admin"))
            self.assertEqual([item.reference for item in platform_items], ["CCCCCCCCCCCC"])
            self.assertEqual(platform_items[0].requester_role, "teacher")
            self.assertEqual(platform_items[0].institution_name, "Institute A")
            self.assertEqual(platform_items[0].requester_name, "Faculty A")
            with self.assertRaises(HTTPException):
                reply_to_contact("BBBBBBBBBBBB", ContactReply(reply="Please retry."), institution)
            reply_to_contact("AAAAAAAAAAAA", ContactReply(reply="Please retry."), institution)
        self.assertEqual(rows[0]["reply"], "Please retry.")
        self.assertIsNone(rows[1]["reply"])
        self.assertIsNone(rows[2]["reply"])

    def test_non_admin_cannot_use_staff_inbox(self) -> None:
        for role in ("student", "teacher"):
            with self.subTest(role=role), self.assertRaises(HTTPException) as caught:
                support_inbox(_profile(f"{role}-a", "tenant-a", role))
            self.assertEqual(caught.exception.status_code, 403)

    def test_migration_keeps_contact_table_private_and_cascades_erasure(self) -> None:
        migration = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "migration-60-student-contact.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("enable row level security", migration)
        self.assertIn("from public, anon, authenticated", migration)
        self.assertIn("foreign key (student_id, tenant_id)", migration)
        self.assertIn("on delete cascade", migration)
        self.assertIn("student_contact_requests_route_check", migration)

    def test_atomic_submission_function_is_service_role_only(self) -> None:
        migration = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "migration-62-atomic-student-contact.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("for update", migration)
        self.assertIn("security invoker", migration)
        self.assertIn("from public, anon, authenticated", migration)
        self.assertIn("to service_role", migration)

    def test_role_aware_support_migration_preserves_history_and_privacy(self) -> None:
        migration = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "migration-74-role-aware-support.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("rename column student_id to requester_id", migration)
        self.assertIn("set requester_role = 'student'", migration)
        self.assertIn("profile.role::text = p_requester_role", migration)
        self.assertIn("for update", migration)
        self.assertIn("from public, anon, authenticated", migration)
        self.assertIn("to service_role", migration)
        self.assertIn("submit_student_contact", migration)


if __name__ == "__main__":
    unittest.main()
