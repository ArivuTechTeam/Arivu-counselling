from __future__ import annotations

import asyncio
import re
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.admin import (
    TeacherCreate,
    TemporaryPasswordReset,
    TeacherUpdate,
    _assert_tenant_course,
    _tenant_course_exists,
    _validated_subject_ids,
    delete_user,
    get_course_impact,
    list_course_students,
    list_teacher_courses,
    list_users,
    reset_teacher_temporary_password,
    update_user,
)
from app.api.institution_admin import router as institution_admin_router
from app.api.academics import list_courses
from app.api.teacher import class_overview
from app.lib.auth import CurrentProfile


def temporary_password() -> str:
    return f"{uuid4().hex}Aa1!"


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.in_filters: list[tuple[str, set[object]]] = []
        self.single = False
        self.updates: dict | None = None
        self.deleting = False
        self.inserts: list[dict] | None = None

    def select(self, _columns: str, **kwargs):
        self.with_count = kwargs.get("count") == "exact"
        return self

    def ilike(self, column: str, value: str):
        self.ilike_filter = (column, value.strip("%").lower())
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
        self.start = start
        self.end = end
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, values: dict):
        self.updates = values
        return self

    def delete(self):
        self.deleting = True
        return self

    def insert(self, values):
        self.inserts = values if isinstance(values, list) else [values]
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.in_filters:
            rows = [row for row in rows if row.get(column) in values]
        if hasattr(self, "ilike_filter"):
            column, value = self.ilike_filter
            rows = [row for row in rows if value in str(row.get(column) or "").lower()]
        total = len(rows)
        if self.updates is not None:
            for row in rows:
                row.update(self.updates)
        if self.deleting:
            deleted_ids = {id(row) for row in rows}
            self.rows[:] = [row for row in self.rows if id(row) not in deleted_ids]
        if self.inserts is not None:
            self.rows.extend(dict(row) for row in self.inserts)
            rows = self.inserts
        result = [dict(row) for row in rows]
        if hasattr(self, "start"):
            result = result[self.start : self.end + 1]
        return SimpleNamespace(
            data=(result[0] if result else None) if self.single else result,
            count=total if getattr(self, "with_count", False) else None,
        )


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

    def delete_user(self, user_id: str):
        self.users[:] = [user for user in self.users if user.id != user_id]


class _Rpc:
    def __init__(self, data: list[str]) -> None:
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _Service:
    def __init__(self) -> None:
        self.queries: list[str] = []
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
            "chapters": [],
            "documents": [],
            "quiz_sets": [],
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
        self.queries.append(name)
        return _Query(self.tables[name])

    def rpc(self, name: str, params: dict) -> _Rpc:
        if name == "anonymize_account_data":
            return _Rpc([])
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
        teachers = list_users(profile=self.profile).items

        self.assertEqual({teacher.id for teacher in teachers}, {"teacher-a", "teacher-enrolled"})
        assigned = next(teacher for teacher in teachers if teacher.id == "teacher-a")
        self.assertEqual(assigned.courses, ["First Year"])
        self.assertEqual(assigned.subject_count, 1)
        self.assertEqual(teachers[0].id, "teacher-enrolled")

    def test_teacher_creation_requires_the_temporary_password_policy(self) -> None:
        with self.assertRaises(ValidationError):
            TeacherCreate(
                full_name="Ada",
                email="ada@example.com",
                password="weak",
                course_id="course-a",
                subject_ids=["subject-a"],
            )

    def test_course_delete_impact_counts_only_tenant_students(self) -> None:
        impact = get_course_impact("course-a", self.profile)

        self.assertEqual(impact.subjects, 1)
        self.assertEqual(impact.students, 1)
        self.assertEqual(impact.teacher_assignments, 1)

    def test_teacher_directory_is_bounded_and_pageable(self) -> None:
        first_page = list_users(page=1, page_size=1, profile=self.profile).items
        second_page = list_users(page=2, page_size=1, profile=self.profile).items

        self.assertEqual(len(first_page), 1)
        self.assertEqual(len(second_page), 1)
        self.assertNotEqual(first_page[0].id, second_page[0].id)

        with self.assertRaises(HTTPException) as error:
            list_users(page=1, page_size=101, profile=self.profile)
        self.assertEqual(error.exception.status_code, 400)

    def test_teacher_course_counts_only_student_enrollments(self) -> None:
        courses = list_teacher_courses("teacher-a", self.profile)

        self.assertEqual(len(courses), 1)
        self.assertEqual(courses[0]["name"], "First Year")
        self.assertEqual(courses[0]["student_count"], 1)
        self.assertEqual(courses[0]["subjects"], [{"id": "subject-a", "name": "Mathematics"}])

    def test_course_listing_batches_subjects_in_one_query(self) -> None:
        self.service.tables["courses"].extend(
            [
                {"id": "course-c", "tenant_id": "tenant-a", "name": "Second Year"},
                {"id": "course-d", "tenant_id": "tenant-a", "name": "Third Year"},
            ]
        )
        self.service.tables["subjects"].extend(
            [
                {"id": "subject-c", "tenant_id": "tenant-a", "course_id": "course-c", "name": "Tax"},
                {"id": "subject-d", "tenant_id": "tenant-a", "course_id": "course-d", "name": "Audit"},
            ]
        )
        self.service.queries.clear()

        with patch("app.api.academics.get_service_client", return_value=self.service):
            courses = list_courses(self.profile)

        self.assertEqual(len(courses), 3)
        self.assertEqual(self.service.queries.count("subjects"), 1)
        self.assertEqual(
            self.service.queries,
            ["courses", "subjects", "enrollments", "profiles"],
        )

    def test_course_listing_preserves_catalog_level_for_teacher_assignment(self) -> None:
        self.service.tables["subjects"][0]["catalog_subject_id"] = "catalog-subject-a"
        self.service.tables["catalog_course_subjects"] = [
            {"id": "catalog-subject-a", "catalog_level_id": "catalog-level-a"}
        ]
        self.service.tables["catalog_course_levels"] = [
            {"id": "catalog-level-a", "name": "Level 1"}
        ]

        with patch("app.api.academics.get_service_client", return_value=self.service):
            courses = list_courses(self.profile)

        subject = courses[0]["subjects"][0]
        self.assertEqual(subject["catalog_subject_id"], "catalog-subject-a")
        self.assertEqual(subject["catalog_level_id"], "catalog-level-a")
        self.assertEqual(subject["level_name"], "Level 1")

    def test_teacher_overview_reuses_content_counts_when_no_variant_exists(self) -> None:
        self.service.tables.update(
            {
                "quiz_sets": [
                    {"id": "set-a", "tenant_id": "tenant-a", "created_by": "teacher-a", "title": "Draft", "status": "draft"},
                    {"id": "set-b", "tenant_id": "tenant-b", "created_by": "teacher-b", "title": "Other", "status": "published"},
                ],
                "documents": [
                    {"id": "doc-a", "tenant_id": "tenant-a", "uploaded_by": "teacher-a"},
                    {"id": "doc-b", "tenant_id": "tenant-b", "uploaded_by": "teacher-b"},
                ],
                "quiz_variants": [],
            }
        )
        teacher = CurrentProfile(
            user_id="teacher-a", tenant_id="tenant-a", role="teacher"
        )
        self.service.queries.clear()

        with patch("app.api.teacher.get_service_client", return_value=self.service):
            result = asyncio.run(class_overview(teacher))

        self.assertEqual(
            result["content"],
            {"documents": 1, "quiz_sets": 1, "published": 0, "drafts": 1},
        )
        self.assertEqual(
            Counter(self.service.queries),
            Counter({"quiz_sets": 1, "documents": 1, "quiz_variants": 1}),
        )

    def test_course_roster_excludes_teachers_and_other_tenants(self) -> None:
        roster = list_course_students("course-a", self.profile)

        self.assertEqual(roster["count"], 1)
        self.assertEqual([student["id"] for student in roster["students"]], ["student-a"])
        self.assertEqual(roster["students"][0]["email"], "student-a@example.com")

    def test_course_lookup_only_selects_columns_that_exist_on_courses(self) -> None:
        service = MagicMock()
        query = service.table.return_value
        query.select.return_value = query
        query.eq.return_value = query
        query.maybe_single.return_value = query
        query.execute.return_value = SimpleNamespace(
            data={"id": "course-a", "name": "First Year"}
        )

        course = _assert_tenant_course(
            service, course_id="course-a", tenant_id="tenant-a"
        )

        service.table.assert_called_once_with("courses")
        query.select.assert_called_once_with("id, name")
        self.assertEqual(course, {"id": "course-a", "name": "First Year"})

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
                password=temporary_password(),
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

        self.assertEqual(result, {"changed": True})
        profile = next(row for row in self.service.tables["profiles"] if row["id"] == "teacher-a")
        self.assertEqual(profile["full_name"], "Ada Updated")
        auth_user = self.service.auth.admin.get_user_by_id("teacher-a").user
        self.assertEqual(auth_user.email, "ada.updated@example.com")
        self.assertEqual(auth_user.user_metadata["tenant_id"], "tenant-a")
        self.assertEqual(auth_user.user_metadata["full_name"], "Ada Updated")

    def test_temporary_password_is_accepted_but_never_returned(self) -> None:
        generated = temporary_password()
        result = reset_teacher_temporary_password(
            "teacher-a", TemporaryPasswordReset(password=generated), self.profile
        )

        self.assertTrue(result.changed)
        self.assertFalse(hasattr(result, "password"))
        self.assertFalse(hasattr(result, "email"))
        auth_user = self.service.auth.admin.get_user_by_id("teacher-a").user
        self.assertEqual(auth_user.password, generated)
        self.assertTrue(auth_user.user_metadata["must_change_password"])
        teacher = next(row for row in self.service.tables["profiles"] if row["id"] == "teacher-a")
        self.assertTrue(teacher["must_change_password"])

    def test_cross_tenant_teacher_password_cannot_be_reset(self) -> None:
        with self.assertRaises(HTTPException) as error:
            reset_teacher_temporary_password(
                "teacher-b",
                TemporaryPasswordReset(password=temporary_password()),
                self.profile,
            )

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
