from __future__ import annotations

import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.api.admin import (
    TeacherCreate,
    TeacherUpdate,
    _generate_temporary_password,
    _tenant_course_exists,
    _validated_subject_ids,
    delete_user,
    list_course_students,
    list_teacher_courses,
    list_users,
    reset_teacher_temporary_password,
    update_user,
)
from app.api.institution_admin import router as institution_admin_router
from app.lib.auth import CurrentProfile


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.single = False
        self.updates: dict | None = None

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[object]):
        self.in_filters.append((column, set(values)))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, values: dict):
        self.updates = values
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.in_filters:
            rows = [row for row in rows if row.get(column) in values]
        if self.updates is not None:
            for row in rows:
                row.update(self.updates)
        result = [dict(row) for row in rows]
        return SimpleNamespace(data=(result[0] if result else None) if self.single else result)


class _AuthAdmin:
    def __init__(self, users: list) -> None:
        self.users = users

    def list_users(self, *, page: int, per_page: int):
        start = (page - 1) * per_page
        return self.users[start : start + per_page]

    def get_user_by_id(self, user_id: str):
        user = next(user for user in self.users if user.id == user_id)
        return SimpleNamespace(user=user)

    def update_user_by_id(self, user_id: str, attributes: dict):
        user = next(user for user in self.users if user.id == user_id)
        if "email" in attributes:
            user.email = attributes["email"]
        if "user_metadata" in attributes:
            user.user_metadata = attributes["user_metadata"]
        if "password" in attributes:
            user.password = attributes["password"]
        return SimpleNamespace(user=user)


class _Rpc:
    def __init__(self, data: list[str]) -> None:
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _Service:
    def __init__(self) -> None:
        self.tables = {
            "profiles": [
                {"id": "teacher-a", "tenant_id": "tenant-a", "role": "teacher", "full_name": "Ada Teacher", "created_at": "2026-09-07T10:00:00Z"},
                {"id": "student-a", "tenant_id": "tenant-a", "role": "student", "full_name": "Sam Student"},
                {"id": "teacher-enrolled", "tenant_id": "tenant-a", "role": "teacher", "full_name": "Terry Teacher", "created_at": "2026-09-08T10:00:00Z"},
                {"id": "teacher-b", "tenant_id": "tenant-b", "role": "teacher", "full_name": "Other Teacher"},
                {"id": "student-b", "tenant_id": "tenant-b", "role": "student", "full_name": "Other Student"},
            ],
            "teacher_subjects": [
                {"tenant_id": "tenant-a", "teacher_id": "teacher-a", "subject_id": "subject-a"},
                {"tenant_id": "tenant-b", "teacher_id": "teacher-b", "subject_id": "subject-b"},
            ],
            "subjects": [
                {"id": "subject-a", "tenant_id": "tenant-a", "course_id": "course-a", "name": "Mathematics"},
                {"id": "subject-b", "tenant_id": "tenant-b", "course_id": "course-b", "name": "Physics"},
            ],
            "courses": [
                {"id": "course-a", "tenant_id": "tenant-a", "name": "First Year"},
                {"id": "course-b", "tenant_id": "tenant-b", "name": "Other College"},
            ],
            "enrollments": [
                {"tenant_id": "tenant-a", "profile_id": "student-a", "course_id": "course-a"},
                {"tenant_id": "tenant-a", "profile_id": "teacher-enrolled", "course_id": "course-a"},
                {"tenant_id": "tenant-b", "profile_id": "student-b", "course_id": "course-b"},
            ],
        }
        users = [
            SimpleNamespace(
                id=row["id"],
                email=f'{row["id"]}@example.com',
                user_metadata={"tenant_id": row["tenant_id"]},
            )
            for row in self.tables["profiles"]
        ]
        self.auth = SimpleNamespace(admin=_AuthAdmin(users))

    def table(self, name: str) -> _Query:
        return _Query(self.tables[name])

    def rpc(self, name: str, params: dict) -> _Rpc:
        if name != "replace_teacher_subjects":
            raise AssertionError(f"Unexpected RPC: {name}")
        return _Rpc(params["p_subject_ids"])


class InstitutionTeacherManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _Service()
        self.profile = CurrentProfile(
            user_id="admin-a", tenant_id="tenant-a", role="institution_admin"
        )
        self.service_patch = patch(
            "app.api.admin.get_service_client", return_value=self.service
        )
        self.service_patch.start()

    def tearDown(self) -> None:
        self.service_patch.stop()

    def test_teacher_list_excludes_students_and_other_tenants(self) -> None:
        teachers = list_users(self.profile)

        self.assertEqual({teacher["id"] for teacher in teachers}, {"teacher-a", "teacher-enrolled"})
        assigned = next(teacher for teacher in teachers if teacher["id"] == "teacher-a")
        self.assertEqual(assigned["courses"], ["First Year"])
        self.assertEqual(assigned["subject_count"], 1)
        self.assertEqual(teachers[0]["id"], "teacher-enrolled")

    def test_teacher_course_counts_only_student_enrollments(self) -> None:
        courses = list_teacher_courses("teacher-a", self.profile)

        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["name"], "First Year")
        self.assertEqual(courses[0]["student_count"], 1)
        self.assertEqual(courses[0]["subjects"], [{"id": "subject-a", "name": "Mathematics"}])

    def test_course_roster_excludes_teachers_and_other_tenants(self) -> None:
        roster = list_course_students("course-a", self.profile)

        self.assertEqual(roster["count"], 1)
        self.assertEqual([student["id"] for student in roster["students"]], ["student-a"])
        self.assertEqual(roster["students"][0]["email"], "student-a@example.com")

    def test_cross_tenant_teacher_and_course_are_not_visible(self) -> None:
        with self.assertRaises(HTTPException) as teacher_error:
            list_teacher_courses("teacher-b", self.profile)
        self.assertEqual(teacher_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as course_error:
            list_course_students("course-b", self.profile)
        self.assertEqual(course_error.exception.status_code, 404)

    def test_teacher_create_contract_rejects_student_role_and_course(self) -> None:
        with self.assertRaises(ValidationError):
            TeacherCreate(
                full_name="Student",
                email="student@example.com",
                password="password",
                role="student",
                course_id="course-a",
                subject_ids=["subject-a"],
            )

    def test_teacher_provisioning_uses_selected_course_from_admin_tenant(self) -> None:
        course_id = _tenant_course_exists(self.service, "tenant-a", "course-a")

        self.assertEqual(course_id, "course-a")

    def test_teacher_provisioning_rejects_cross_tenant_course(self) -> None:
        with self.assertRaises(HTTPException) as error:
            _tenant_course_exists(self.service, "tenant-a", "course-b")

        self.assertEqual(error.exception.status_code, 400)

    def test_create_assignments_must_match_selected_course_and_tenant(self) -> None:
        self.assertEqual(
            _validated_subject_ids(
                self.service,
                tenant_id="tenant-a",
                course_id="course-a",
                subject_ids=["subject-a", "subject-a"],
            ),
            ["subject-a"],
        )
        with self.assertRaises(HTTPException) as tenant_error:
            _validated_subject_ids(
                self.service,
                tenant_id="tenant-a",
                course_id="course-a",
                subject_ids=["subject-b"],
            )
        self.assertEqual(tenant_error.exception.status_code, 400)

    def test_cross_tenant_teacher_cannot_be_edited(self) -> None:
        with self.assertRaises(HTTPException) as error:
            update_user(
                "teacher-b",
                TeacherUpdate(
                    full_name="Changed",
                    email="changed@example.com",
                    subject_ids=["subject-a"],
                ),
                self.profile,
            )

        self.assertEqual(error.exception.status_code, 404)

    def test_teacher_identity_and_assignments_can_be_edited(self) -> None:
        result = update_user(
            "teacher-a",
            TeacherUpdate(
                full_name="Ada Updated",
                email="ada.updated@example.com",
                subject_ids=["subject-a"],
            ),
            self.profile,
        )

        self.assertEqual(result["full_name"], "Ada Updated")
        self.assertEqual(result["email"], "ada.updated@example.com")
        profile = next(row for row in self.service.tables["profiles"] if row["id"] == "teacher-a")
        self.assertEqual(profile["full_name"], "Ada Updated")
        auth_user = self.service.auth.admin.get_user_by_id("teacher-a").user
        self.assertEqual(auth_user.email, "ada.updated@example.com")
        self.assertEqual(auth_user.user_metadata["tenant_id"], "tenant-a")
        self.assertEqual(auth_user.user_metadata["full_name"], "Ada Updated")

    def test_temporary_password_is_strong_and_reset_for_tenant_teacher(self) -> None:
        generated = _generate_temporary_password()
        self.assertEqual(len(generated), 14)
        for pattern in (r"[A-Z]", r"[a-z]", r"[0-9]", r"[!@#$%]"):
            self.assertRegex(generated, pattern)

        response = Response()
        result = reset_teacher_temporary_password(
            "teacher-a", response, self.profile
        )

        self.assertEqual(result.email, "teacher-a@example.com")
        self.assertEqual(len(result.password), 14)
        self.assertEqual(response.headers["cache-control"], "no-store, private")
        self.assertEqual(response.headers["pragma"], "no-cache")
        auth_user = self.service.auth.admin.get_user_by_id("teacher-a").user
        self.assertEqual(auth_user.password, result.password)
        teacher = next(row for row in self.service.tables["profiles"] if row["id"] == "teacher-a")
        self.assertTrue(teacher["must_change_password"])

    def test_cross_tenant_teacher_password_cannot_be_reset(self) -> None:
        with self.assertRaises(HTTPException) as error:
            reset_teacher_temporary_password("teacher-b", Response(), self.profile)

        self.assertEqual(error.exception.status_code, 404)

    def test_temporary_password_endpoint_is_registered(self) -> None:
        registered = {
            (route.path, method)
            for route in institution_admin_router.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(
            ("/api/v1/users/{user_id}/temporary-password", "POST"),
            registered,
        )

    def test_student_cannot_be_deleted_through_teacher_management(self) -> None:
        with self.assertRaises(HTTPException) as error:
            delete_user("student-a", self.profile)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Only teachers can be removed here.")


if __name__ == "__main__":
    unittest.main()
