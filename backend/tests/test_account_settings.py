from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api.auth_account import account_settings
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = [dict(row) for row in rows]

    def select(self, _columns: str) -> "_Query":
        return self

    def eq(self, column: str, value: str) -> "_Query":
        self.rows = [row for row in self.rows if str(row.get(column)) == str(value)]
        return self

    def in_(self, column: str, values: list[str]) -> "_Query":
        allowed = {str(value) for value in values}
        self.rows = [row for row in self.rows if str(row.get(column)) in allowed]
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)


class _Service:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables

    def table(self, name: str) -> _Query:
        return _Query(self.tables.get(name, []))


class AccountSettingsTests(unittest.TestCase):
    def test_student_sees_only_own_tenant_course_level_and_subjects(self) -> None:
        service = _Service(
            {
                "enrollments": [
                    {
                        "tenant_id": "tenant-a",
                        "profile_id": "student-a",
                        "course_id": "course-a",
                        "course_level_id": "level-a",
                    },
                    {
                        "tenant_id": "tenant-a",
                        "profile_id": "student-b",
                        "course_id": "course-b",
                        "course_level_id": "level-b",
                    },
                ],
                "courses": [
                    {
                        "id": "course-a",
                        "tenant_id": "tenant-a",
                        "name": "CA",
                    },
                    {
                        "id": "course-a",
                        "tenant_id": "tenant-b",
                        "name": "Wrong tenant",
                    },
                ],
                "course_levels": [
                    {
                        "id": "level-a",
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "name": "Foundation",
                    },
                ],
                "subjects": [
                    {
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "course_level_id": "level-a",
                        "name": "Accounting",
                    },
                    {
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "course_level_id": "level-b",
                        "name": "Final subject",
                    },
                    {
                        "tenant_id": "tenant-b",
                        "course_id": "course-a",
                        "course_level_id": "level-a",
                        "name": "Wrong tenant subject",
                    },
                ],
            }
        )
        profile = CurrentProfile(
            user_id="student-a",
            tenant_id="tenant-a",
            role="student",
            full_name="Student A",
            email="student@example.com",
        )

        with patch("app.api.auth_account.get_service_client", return_value=service):
            result = account_settings(profile)

        self.assertEqual(result.full_name, "Student A")
        self.assertEqual(result.role, "student")
        self.assertEqual(
            [access.model_dump() for access in result.academic_access],
            [
                {
                    "course": "CA",
                    "level": "Foundation",
                    "subjects": ["Accounting"],
                }
            ],
        )

    def test_teacher_access_is_derived_from_explicit_subject_assignments(self) -> None:
        service = _Service(
            {
                "teacher_subjects": [
                    {
                        "tenant_id": "tenant-a",
                        "teacher_id": "teacher-a",
                        "subject_id": "subject-a",
                    },
                    {
                        "tenant_id": "tenant-a",
                        "teacher_id": "teacher-b",
                        "subject_id": "subject-b",
                    },
                ],
                "subjects": [
                    {
                        "id": "subject-a",
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "course_level_id": "level-a",
                        "name": "Accounting",
                    },
                    {
                        "id": "subject-b",
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "course_level_id": "level-a",
                        "name": "Economics",
                    },
                ],
                "courses": [
                    {"id": "course-a", "tenant_id": "tenant-a", "name": "CA"},
                ],
                "course_levels": [
                    {
                        "id": "level-a",
                        "tenant_id": "tenant-a",
                        "course_id": "course-a",
                        "name": "Foundation",
                    },
                ],
            }
        )
        profile = CurrentProfile(
            user_id="teacher-a",
            tenant_id="tenant-a",
            role="teacher",
            full_name="Teacher A",
            email="teacher@example.com",
        )

        with patch("app.api.auth_account.get_service_client", return_value=service):
            result = account_settings(profile)

        self.assertEqual(
            [access.model_dump() for access in result.academic_access],
            [
                {
                    "course": "CA",
                    "level": "Foundation",
                    "subjects": ["Accounting"],
                }
            ],
        )

    def test_administrator_has_profile_settings_without_academic_queries(self) -> None:
        service = _Service({})
        profile = CurrentProfile(
            user_id="admin-a",
            tenant_id="tenant-a",
            role="institution_admin",
            full_name="Admin A",
            email="admin@example.com",
        )

        with patch("app.api.auth_account.get_service_client", return_value=service):
            result = account_settings(profile)

        self.assertEqual(result.role, "institution_admin")
        self.assertEqual(result.academic_access, [])


if __name__ == "__main__":
    unittest.main()
