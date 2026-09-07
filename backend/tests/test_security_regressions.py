from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.academics import _require_admin
from app.api.documents import _require_teacher as require_document_teacher
from app.api.practice import _exam_deadline_passed
from app.api.questions import _require_teacher as require_question_teacher
from app.api.quiz import _require_teacher as require_quiz_teacher
from app.lib.auth import CurrentProfile, CurrentUser, get_current_profile
from app.services.blueprint import generate_blueprint_quiz
from app.services.generation import generate_quiz
from app.services.teacher_access import teacher_has_subject


def profile(role: str) -> CurrentProfile:
    return CurrentProfile(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        role=role,
    )


class RoleGuardTests(unittest.TestCase):
    def test_teacher_content_guards_reject_other_roles(self) -> None:
        guards = [require_document_teacher, require_question_teacher, require_quiz_teacher]
        for guard in guards:
            guard(profile("teacher"))
            for role in ("student", "institution_admin", "super_admin"):
                with self.subTest(guard=guard.__module__, role=role):
                    with self.assertRaises(HTTPException) as caught:
                        guard(profile(role))
                    self.assertEqual(caught.exception.status_code, 403)

    def test_course_management_is_institution_admin_only(self) -> None:
        _require_admin(profile("institution_admin"))
        for role in ("student", "teacher", "super_admin"):
            with self.subTest(role=role):
                with self.assertRaises(HTTPException) as caught:
                    _require_admin(profile(role))
                self.assertEqual(caught.exception.status_code, 403)


class ExamDeadlineTests(unittest.TestCase):
    def test_exam_deadline_is_enforced_with_network_grace(self) -> None:
        session = {
            "mode": "exam",
            "started_at": "2026-09-05T10:00:00Z",
            "config": {"duration_minutes": 60},
        }
        self.assertFalse(
            _exam_deadline_passed(
                session, datetime(2026, 9, 5, 11, 0, 5, tzinfo=timezone.utc)
            )
        )
        self.assertTrue(
            _exam_deadline_passed(
                session, datetime(2026, 9, 5, 11, 0, 11, tzinfo=timezone.utc)
            )
        )

    def test_non_exam_has_no_deadline(self) -> None:
        self.assertFalse(
            _exam_deadline_passed(
                {"mode": "smart", "config": {"duration_minutes": 1}}
            )
        )


class MigrationSecurityTests(unittest.TestCase):
    def test_auth_migration_ignores_requested_role_and_locks_profile_columns(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (root / "migrations/migration-11-auth-hardening.sql").read_text()
        self.assertIn("'student'::user_role", sql)
        self.assertNotIn("new.raw_user_meta_data->>'role')::user_role", sql)
        self.assertIn("new.raw_app_meta_data->>'provisioned_by_backend'", sql)
        self.assertIn("select c.tenant_id into selected_tenant", sql.lower())
        self.assertIn("revoke update on table profiles from authenticated", sql.lower())
        self.assertIn("grant update (full_name, avatar_url)", sql.lower())
        self.assertIn("must_change_password boolean not null default false", sql.lower())

    def test_teacher_subject_migration_is_tenant_safe_and_atomic(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (root / "migrations/migration-12-teacher-subjects.sql").read_text().lower()
        self.assertIn("foreign key (teacher_id, tenant_id)", sql)
        self.assertIn("foreign key (subject_id, tenant_id)", sql)
        self.assertIn("create policy \"read permitted teacher subjects\"", sql)
        self.assertIn("create or replace function public.replace_teacher_subjects", sql)
        self.assertIn("set search_path = ''", sql)
        self.assertIn("revoke all on function public.replace_teacher_subjects", sql)
        self.assertIn('drop policy if exists "staff manage enrollments"', sql)


class _RowsQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows[0] if self.rows else None)


class _RowsService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def table(self, table: str) -> _RowsQuery:
        if table != "teacher_subjects":
            raise AssertionError(f"Unexpected table access: {table}")
        return _RowsQuery(self.rows)


class TeacherSubjectAuthorizationTests(unittest.TestCase):
    def test_explicit_assignment_is_required(self) -> None:
        teacher = profile("teacher")
        self.assertFalse(teacher_has_subject(_RowsService([]), teacher, "subject-1"))
        self.assertTrue(
            teacher_has_subject(
                _RowsService([{"subject_id": "subject-1"}]), teacher, "subject-1"
            )
        )

    def test_unassigned_subject_stops_both_generation_paths_early(self) -> None:
        teacher = profile("teacher")
        with patch(
            "app.services.generation.get_service_client",
            return_value=_RowsService([]),
        ):
            with self.assertRaisesRegex(ValueError, "Subject not found"):
                generate_quiz(
                    document_id="document-1",
                    num_questions=1,
                    question_types=["mcq_single"],
                    cognitive_level="mixed",
                    difficulty="medium",
                    profile=teacher,
                    subject_id="subject-1",
                )

        with patch(
            "app.services.blueprint.get_service_client",
            return_value=_RowsService([]),
        ):
            with self.assertRaisesRegex(ValueError, "Subject not found"):
                generate_blueprint_quiz(
                    document_id="document-1",
                    subject_id="subject-1",
                    chapter_name="Chapter",
                    selected_topics=[],
                    total_questions=1,
                    question_types=["mcq_single"],
                    cognitive_level="mixed",
                    difficulty="medium",
                    profile=teacher,
                )


class _ProfileQuery:
    def __init__(self, row: dict) -> None:
        self.row = row

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return SimpleNamespace(data=self.row)


class PasswordGateTests(unittest.TestCase):
    def test_forced_password_blocks_other_backend_actions(self) -> None:
        row = {
            "id": "u1",
            "tenant_id": "t1",
            "role": "teacher",
            "full_name": "Teacher",
            "must_change_password": True,
        }
        service = SimpleNamespace(table=lambda _name: _ProfileQuery(row))
        user = CurrentUser(user_id="u1", email="teacher@example.com")
        with patch("app.lib.auth.get_service_client", return_value=service):
            request = Request({"type": "http", "method": "GET", "path": "/api/v1/documents", "headers": []})
            with self.assertRaises(HTTPException) as caught:
                get_current_profile(request, user)
            self.assertEqual(caught.exception.status_code, 403)

            change_request = Request({"type": "http", "method": "POST", "path": "/api/v1/auth/change-password", "headers": []})
            profile = get_current_profile(change_request, user)
            self.assertTrue(profile.must_change_password)


if __name__ == "__main__":
    unittest.main()
