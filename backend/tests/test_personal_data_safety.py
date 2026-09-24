from __future__ import annotations

import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth_account import (
    AccountDeletion,
    delete_own_account,
)
from app.api.questions import QuestionOut
from app.lib.auth import CurrentProfile
from app.services.account_deletion import erase_account_data


class _RpcCall:
    def __init__(self, service: "_DeletionService") -> None:
        self.service = service

    def execute(self) -> SimpleNamespace:
        self.service.actions.append(("execute_anonymization",))
        return SimpleNamespace(data=None)


class _AuthAdmin:
    def __init__(self, service: "_DeletionService") -> None:
        self.service = service

    def sign_out(self, token: str, scope: str) -> None:
        self.service.actions.append(("sign_out", token, scope))

    def delete_user(self, user_id: str) -> None:
        self.service.actions.append(("delete_user", user_id))


class _DeletionService:
    def __init__(self) -> None:
        self.actions: list[tuple] = []
        self.auth = SimpleNamespace(admin=_AuthAdmin(self))

    def rpc(self, name: str, params: dict) -> _RpcCall:
        self.actions.append(("rpc", name, params))
        return _RpcCall(self)


class _DocumentQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def select(self, _columns: str) -> "_DocumentQuery":
        return self

    def eq(self, _column: str, _value: str) -> "_DocumentQuery":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)


class AccountDeletionTests(unittest.TestCase):
    profile = CurrentProfile(
        user_id="user-a",
        tenant_id="tenant-a",
        role="student",
        email="student@example.com",
        full_name="Student A",
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="private-session-token",
    )

    def test_shared_erasure_removes_storage_before_database_data(self) -> None:
        service = _DeletionService()
        service.table = lambda _name: _DocumentQuery(
            [
                {"storage_path": "tenant-a/object-a.pdf"},
                {"storage_path": "tenant-a/object-a.pdf"},
            ]
        )
        with patch(
            "app.services.account_deletion.delete_bytes",
            side_effect=lambda _path: service.actions.append(("delete_storage",)),
        ):
            erase_account_data(service, user_id="user-a", tenant_id="tenant-a")

        self.assertEqual(
            service.actions,
            [
                ("delete_storage",),
                (
                    "rpc",
                    "anonymize_account_data",
                    {"p_user_id": "user-a", "p_tenant_id": "tenant-a"},
                ),
                ("execute_anonymization",),
            ],
        )

    def test_account_deletion_revokes_sessions_before_data_and_identity(self) -> None:
        service = _DeletionService()
        with patch(
            "app.api.auth_account.get_service_client", return_value=service
        ), patch(
            "app.api.auth_account.erase_account_data",
            side_effect=lambda *_args, **_kwargs: service.actions.append(
                ("erase_account_data",)
            ),
        ):
            result = delete_own_account(
                AccountDeletion(confirmation="DELETE"),
                self.credentials,
                self.profile,
            )

        self.assertTrue(result.deleted)
        self.assertEqual(
            service.actions,
            [
                ("sign_out", "private-session-token", "global"),
                ("erase_account_data",),
                ("delete_user", "user-a"),
            ],
        )
        self.assertEqual(result.model_dump(), {"deleted": True})

    def test_session_revocation_failure_stops_deletion(self) -> None:
        service = _DeletionService()

        def fail_sign_out(_token: str, scope: str) -> None:
            del scope
            raise RuntimeError("provider payload with personal data")

        service.auth.admin.sign_out = fail_sign_out
        with patch(
            "app.api.auth_account.get_service_client", return_value=service
        ), self.assertRaises(HTTPException) as caught:
            delete_own_account(
                AccountDeletion(confirmation="DELETE"),
                self.credentials,
                self.profile,
            )

        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("personal data", caught.exception.detail)
        self.assertFalse(any(action[0] == "rpc" for action in service.actions))

    def test_figure_cleanup_failure_stops_anonymization_and_identity_deletion(self) -> None:
        service = _DeletionService()
        service.table = lambda _name: _DocumentQuery([
            {"id": "document-a", "storage_path": None},
        ])
        with patch(
            "app.api.auth_account.get_service_client", return_value=service
        ), patch(
            "app.services.document_figures.purge_figures_for_documents",
            side_effect=RuntimeError("storage provider details"),
        ) as purge, self.assertRaises(HTTPException) as caught:
            delete_own_account(
                AccountDeletion(confirmation="DELETE"),
                self.credentials,
                self.profile,
            )

        purge.assert_called_once_with(
            service, tenant_id="tenant-a", document_ids=["document-a"], strict=True
        )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("storage provider details", caught.exception.detail)
        self.assertFalse(any(action[0] == "rpc" for action in service.actions))
        self.assertFalse(any(action[0] == "delete_user" for action in service.actions))


class PersonalDataBoundaryTests(unittest.TestCase):
    def test_migration_erases_activity_and_anonymizes_retained_content(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations" / "migration-30-account-data-deletion.sql"
        ).read_text().lower()
        for table in (
            "quiz_attempts",
            "practice_sessions",
            "bookmarks",
            "revised_topics",
            "enrollments",
            "teacher_subjects",
            "ai_rate_limits",
            "events",
        ):
            self.assertIn(f"delete from public.{table}", sql)
        self.assertIn("set uploaded_by = null", sql)
        self.assertIn("set created_by = null", sql)
        self.assertIn("set reviewed_by = null", sql)
        self.assertIn("creator_name = 'deleted user'", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)

    def test_question_response_model_drops_database_ownership_fields(self) -> None:
        output = QuestionOut.model_validate(
            {
                "id": "question-a",
                "type": "mcq_single",
                "question_text": "Question",
                "options": [],
                "correct_answer": "A",
                "explanation": None,
                "difficulty": "medium",
                "marks": 1,
                "review_status": "approved",
                "tenant_id": "tenant-a",
                "created_by": "user-a",
                "reviewed_by": "user-a",
            }
        ).model_dump()
        self.assertNotIn("tenant_id", output)
        self.assertNotIn("created_by", output)
        self.assertNotIn("reviewed_by", output)

    def test_logs_and_provider_errors_do_not_include_personal_payloads(self) -> None:
        root = Path(__file__).resolve().parents[2]
        main = (root / "backend" / "app" / "main.py").read_text()
        extraction = (
            root / "backend" / "app" / "api" / "extraction.py"
        ).read_text()
        supabase = (
            root / "backend" / "app" / "lib" / "supabase.py"
        ).read_text()
        llm = "\n".join(
            path.read_text()
            for path in (root / "backend" / "app" / "services" / "llm").glob("*.py")
        )
        self.assertNotIn("request.url.path,", main)
        self.assertNotIn("orphaned extraction upload %s", extraction)
        self.assertNotIn("request.url.path,", supabase)
        self.assertNotIn("response.text", llm)
        self.assertNotIn("str(data)", llm)

    def test_local_storage_contains_only_non_personal_theme_preference(self) -> None:
        root = Path(__file__).resolve().parents[2]
        frontend = root / "frontend"
        uses = []
        for path in frontend.rglob("*"):
            if (
                path.is_file()
                and path.suffix in {".ts", ".tsx", ".js", ".mjs"}
                and not any(part in {"node_modules", ".next"} for part in path.parts)
            ):
                text = path.read_text(errors="ignore")
                uses.extend(
                    re.findall(
                        r"localStorage\.(?:getItem|setItem)\(([^)]*)\)",
                        text,
                    )
                )
        self.assertTrue(uses)
        self.assertTrue(all("theme" in expression for expression in uses))


if __name__ == "__main__":
    unittest.main()
