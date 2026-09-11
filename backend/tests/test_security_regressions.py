from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.api.academics import _require_admin
from app.api.auth_account import _validate_new_password
from app.api.documents import _require_teacher as require_document_teacher
from app.api.practice import _exam_deadline_passed
from app.api.questions import _require_teacher as require_question_teacher
from app.api.quiz import _require_teacher as require_quiz_teacher
from app.lib.auth import CurrentProfile, CurrentUser, get_current_profile
from app.lib.api_errors import public_error
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

    def test_google_oauth_signup_still_derives_student_tenant_from_course(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (root / "migrations/migration-14-google-oauth-onboarding.sql").read_text().lower()
        self.assertIn("create or replace function public.complete_google_signup", sql)
        self.assertIn("current_user_id uuid := auth.uid()", sql)
        self.assertIn("where c.id = p_course_id", sql)
        self.assertIn("join public.tenants t on t.id = c.tenant_id and t.is_active = true", sql)
        self.assertIn("'student'::public.user_role", sql)
        self.assertIn("google authentication is required", sql)
        self.assertIn("return query select existing_tenant, existing_role", sql)
        self.assertIn("grant execute on function public.complete_google_signup(uuid)", sql)
        self.assertNotIn("new.raw_user_meta_data->>'role'", sql)

    def test_teacher_deletion_preserves_academic_content(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-20-teacher-deletion-content-retention.sql"
        ).read_text().lower()
        self.assertEqual(sql.count("on delete set null"), 4)
        self.assertIn("alter table public.documents", sql)
        self.assertIn("alter column uploaded_by drop not null", sql)
        self.assertIn("alter table public.questions", sql)
        self.assertIn("alter table public.quiz_sets", sql)
        self.assertIn("alter column created_by drop not null", sql)

    def test_quiz_attempt_limit_is_atomic_and_tenant_scoped(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-24-quiz-attempt-limit.sql"
        ).read_text().lower()
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("count(*) >= p_max_attempts", sql)
        self.assertIn("attempts.tenant_id = p_tenant_id", sql)
        self.assertIn("attempts.student_id = p_student_id", sql)
        self.assertIn("attempts.variant_id = p_variant_id", sql)
        self.assertIn("security invoker", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)

    def test_docker_forwards_student_quiz_attempt_limit(self) -> None:
        root = Path(__file__).resolve().parents[2]
        compose = (root / "docker-compose.yml").read_text()
        root_example = (root / ".env.example").read_text()
        self.assertIn(
            "STUDENT_QUIZ_ATTEMPT_LIMIT: ${STUDENT_QUIZ_ATTEMPT_LIMIT:-2}",
            compose,
        )
        self.assertIn("STUDENT_QUIZ_ATTEMPT_LIMIT=2", root_example)

    def test_revision_topic_snapshot_migration_is_safe_and_additive(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-25-revision-topic-snapshots.sql"
        ).read_text().lower()
        self.assertIn("add column if not exists answered_at_revision", sql)
        self.assertIn("integer not null default 0", sql)
        self.assertIn("check (answered_at_revision >= 0)", sql)
        self.assertIn("from pg_constraint", sql)

    def test_daily_and_exam_session_guards_are_atomic_and_additive(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-26-daily-exam-session-guards.sql"
        ).read_text().lower()
        self.assertIn("add column if not exists activity_date date", sql)
        self.assertIn("add column if not exists active_slot boolean", sql)
        self.assertIn("create unique index if not exists uq_practice_daily_student_date", sql)
        self.assertIn("tenant_id, student_id, activity_date", sql)
        self.assertIn("where mode = 'daily' and activity_date is not null", sql)
        self.assertIn("create unique index if not exists uq_practice_active_exam_student", sql)
        self.assertIn("where mode = 'exam' and status = 'in_progress'", sql)

    def test_challenge_hardening_is_atomic_unique_and_backend_only(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-27-challenge-flow-hardening.sql"
        ).read_text().lower()
        self.assertIn("add column if not exists question_snapshot jsonb", sql)
        self.assertIn("add column if not exists course_ids uuid[]", sql)
        self.assertIn("uq_practice_challenge_participant", sql)
        self.assertIn("challenge_id, student_id", sql)
        self.assertIn("create_challenge_with_session", sql)
        self.assertIn("security invoker", sql)
        self.assertIn("set search_path = ''", sql)
        self.assertIn("from public, anon, authenticated", sql)
        self.assertIn("to service_role", sql)
        self.assertIn("revoke all on table public.challenges", sql)

    def test_docker_forwards_challenge_policy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        compose = (root / "docker-compose.yml").read_text()
        root_example = (root / ".env.example").read_text()
        self.assertIn(
            "CHALLENGE_EXPIRY_DAYS: ${CHALLENGE_EXPIRY_DAYS:-30}", compose
        )
        self.assertIn("CHALLENGE_EXPIRY_DAYS=30", root_example)

    def test_eager_challenge_session_creator_is_removed(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-28-remove-eager-challenge-session.sql"
        ).read_text().lower()
        self.assertIn("drop function if exists", sql)
        self.assertIn("create_challenge_with_session", sql)

    def test_browser_data_api_cannot_expose_quiz_answers(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = (
            root / "migrations/migration-22-browser-data-api-hardening.sql"
        ).read_text().lower()

        self.assertIn('create policy "read own profile"', sql)
        self.assertIn("using (id = auth.uid())", sql)
        self.assertIn("revoke all on table public.profiles", sql)
        self.assertIn("grant select on table public.profiles to authenticated", sql)
        for table in (
            "public.questions",
            "public.quiz_sets",
            "public.quiz_variants",
            "public.quiz_variant_questions",
            "public.quiz_attempts",
            "public.attempt_answers",
            "public.ai_explanations",
            "public.v_student_topic_accuracy",
            "public.v_quiz_question_analysis",
        ):
            self.assertIn(table, sql)
        self.assertIn("from anon, authenticated", sql)
        self.assertEqual(sql.count("security_invoker = true"), 2)
        self.assertIn(
            "revoke all on function public.handle_new_user() from public, anon, authenticated",
            sql,
        )
        self.assertIn(
            "grant execute on function public.complete_google_signup(uuid) to authenticated",
            sql,
        )

    def test_public_error_never_returns_internal_exception_text(self) -> None:
        error = public_error(
            502,
            "Please try again.",
            operation="security regression test",
            exception=RuntimeError("private provider response"),
        )
        self.assertEqual(error.status_code, 502)
        self.assertEqual(error.detail, "Please try again.")
        self.assertNotIn("private provider response", error.detail)


class SecretSafetyTests(unittest.TestCase):
    def test_local_env_files_and_credentials_are_ignored(self) -> None:
        root = Path(__file__).resolve().parents[2]
        gitignore = (root / ".gitignore").read_text()
        self.assertIn(".env", gitignore.splitlines())
        self.assertIn(".env.*", gitignore.splitlines())
        self.assertIn("*.pem", gitignore.splitlines())
        self.assertIn("*credentials*.json", gitignore.splitlines())

        for service in ("backend", "frontend"):
            dockerignore = (root / service / ".dockerignore").read_text()
            self.assertIn(".env*", dockerignore.splitlines())

    def test_frontend_does_not_reference_server_only_environment(self) -> None:
        root = Path(__file__).resolve().parents[2]
        forbidden = (
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_JWT_SECRET",
            "DEEPSEEK_API_KEY",
            "GEMINI_API_KEY",
            "DATABASE_URL",
            "CLIENT_SECRET",
        )
        source_suffixes = {".ts", ".tsx", ".js", ".mjs"}
        for path in (root / "frontend").rglob("*"):
            if path.suffix not in source_suffixes or any(
                part in {"node_modules", ".next", ".pnpm-store"}
                for part in path.parts
            ):
                continue
            contents = path.read_text(errors="ignore")
            for name in forbidden:
                self.assertNotIn(name, contents, f"{name} referenced by {path}")

    def test_repository_has_no_known_credential_literals(self) -> None:
        root = Path(__file__).resolve().parents[2]
        credential_patterns = (
            re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
            re.compile(r"sb_secret_[A-Za-z0-9_-]{12,}"),
            re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{12,}"),
            re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
            re.compile(r"pk_(?:live|test)_[A-Za-z0-9]{12,}"),
            re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
            re.compile(r"(?:postgres(?:ql)?|mongodb(?:\+srv)?|mysql|redis)://[^\s]+"),
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"SG\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
            re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
        )
        text_suffixes = {
            ".py", ".ts", ".tsx", ".js", ".mjs", ".sql", ".md",
            ".yml", ".yaml", ".json", ".sh", ".toml",
        }
        ignored_parts = {
            ".git", ".next", ".pnpm-store", "node_modules", "venv",
            ".venv", ".pytest_cache", ".claude", ".tokensave", ".superdesign",
        }
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix not in text_suffixes
                or any(part in ignored_parts for part in path.parts)
            ):
                continue
            contents = path.read_text(errors="ignore")
            for pattern in credential_patterns:
                self.assertIsNone(pattern.search(contents), f"credential-like literal in {path}")

    def test_every_declared_application_table_enables_rls(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql = "\n".join(
            path.read_text() for path in sorted((root / "migrations").glob("*.sql"))
        )
        created = set(
            re.findall(
                r"(?im)^\s*create\s+table(?:\s+if\s+not\s+exists)?\s+(?:public\.)?([a-z_][a-z0-9_]*)",
                sql,
            )
        )
        protected = set(
            re.findall(
                r"(?im)^\s*alter\s+table(?:\s+if\s+exists)?\s+(?:public\.)?([a-z_][a-z0-9_]*)\s+enable\s+row\s+level\s+security",
                sql,
            )
        )
        self.assertTrue(created)
        self.assertEqual(set(), created - protected)

    def test_backend_logging_does_not_dump_exceptions_or_payloads(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = "\n".join(
            path.read_text() for path in (root / "backend" / "app").rglob("*.py")
        )
        self.assertNotIn("logger.exception(", source)
        self.assertNotIn("log.exception(", source)
        self.assertNotIn("exc_info=True", source)
        self.assertNotIn("%r", source)


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


class PasswordPolicyTests(unittest.TestCase):
    EMAIL = "teacher@example.com"

    def _rejects(self, new: str, current: str = "OldPass1", email: str | None = None):
        with self.assertRaises(HTTPException) as caught:
            _validate_new_password(new, current, email or self.EMAIL)
        self.assertEqual(caught.exception.status_code, 400)

    def test_strong_password_is_accepted(self) -> None:
        # No exception == accepted.
        _validate_new_password("Str0ngPass", "OldPass1", self.EMAIL)

    def test_rejects_weak_or_reused_passwords(self) -> None:
        self._rejects("Ab1cdef")  # too short (7)
        self._rejects("lowercase1")  # no uppercase
        self._rejects("UPPERCASE1")  # no lowercase
        self._rejects("NoDigitsHere")  # no number
        self._rejects("password1")  # common denylist
        self._rejects("Str0ngPass", current="Str0ngPass")  # same as current

    def test_rejects_email_derived_passwords(self) -> None:
        self._rejects("Teacher123")  # contains the email local part "teacher"
        self._rejects(self.EMAIL)  # is the email itself


if __name__ == "__main__":
    unittest.main()
