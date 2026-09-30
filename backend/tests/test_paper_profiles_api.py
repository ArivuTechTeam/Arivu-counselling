from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api import paper_profiles as mod
from app.api.paper_profiles import PaperProfileUpdate
from app.lib.auth import CurrentProfile

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
COURSE = "22222222-2222-2222-2222-222222222222"
LEVEL = "33333333-3333-3333-3333-333333333333"
OTHER_LEVEL = "44444444-4444-4444-4444-444444444444"


def _admin() -> CurrentProfile:
    return CurrentProfile(user_id="admin-1", tenant_id=TENANT, role="institution_admin")


def _teacher() -> CurrentProfile:
    return CurrentProfile(user_id="teacher-1", tenant_id=TENANT, role="teacher")


class _Query:
    def __init__(self, service, table):
        self.service = service
        self.table = table
        self.eqs: list[tuple[str, object]] = []
        self.values: dict | None = None
        self.operation = "select"
        self.single = False

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, values):
        self.operation = "insert"
        self.values = values
        return self

    def update(self, values):
        self.operation = "update"
        self.values = values
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, column, value):
        self.eqs.append((column, value))
        return self

    def in_(self, column, values):
        self.eqs.append((column, set(values)))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def _matches(self, row):
        return all(
            row.get(column) in value if isinstance(value, set) else row.get(column) == value
            for column, value in self.eqs
        )

    def execute(self):
        rows = self.service.data.setdefault(self.table, [])
        if self.operation == "insert":
            row = {"id": f"new-{self.table}", **(self.values or {})}
            rows.append(row)
            return SimpleNamespace(data=[row])
        matched = [row for row in rows if self._matches(row)]
        if self.operation == "update":
            for row in matched:
                row.update(self.values or {})
            return SimpleNamespace(data=matched)
        if self.operation == "delete":
            self.service.data[self.table] = [row for row in rows if not self._matches(row)]
            return SimpleNamespace(data=matched)
        return SimpleNamespace(data=(matched[0] if matched else None) if self.single else matched)


class _Service:
    def __init__(self):
        self.data = {
            "courses": [
                {"id": COURSE, "tenant_id": TENANT, "name": "CA"},
                {"id": "other-course", "tenant_id": OTHER_TENANT, "name": "Secret"},
            ],
            "course_levels": [
                {"id": LEVEL, "tenant_id": TENANT, "course_id": COURSE, "name": "Foundation"},
                {"id": OTHER_LEVEL, "tenant_id": TENANT, "course_id": COURSE, "name": "Final"},
                {
                    "id": "other-tenant-level",
                    "tenant_id": OTHER_TENANT,
                    "course_id": "other-course",
                    "name": "Private",
                },
            ],
            "paper_profiles": [
                {
                    "id": "profile-1",
                    "tenant_id": TENANT,
                    "course_id": COURSE,
                    "course_level_id": LEVEL,
                    "exam_body": "ICAI",
                    "level": "Foundation",
                    "paper": "Paper 4",
                    "assessment_year": "2026",
                    "framework": None,
                    "format_config": {},
                },
                {
                    "id": "other-profile",
                    "tenant_id": OTHER_TENANT,
                    "course_id": "other-course",
                    "course_level_id": "other-tenant-level",
                    "exam_body": "Private",
                },
            ],
        }

    def table(self, name):
        return _Query(self, name)


class PaperProfileApiTests(unittest.TestCase):
    def test_list_is_level_aware_and_tenant_scoped(self):
        service = _Service()
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.list_paper_profiles(_teacher())

        self.assertEqual({row["course_level_id"] for row in result}, {LEVEL, OTHER_LEVEL})
        foundation = next(row for row in result if row["course_level_id"] == LEVEL)
        final = next(row for row in result if row["course_level_id"] == OTHER_LEVEL)
        self.assertEqual(foundation["course_name"], "CA")
        self.assertEqual(foundation["profile"]["exam_body"], "ICAI")
        self.assertIsNone(final["profile"])

    def test_admin_can_update_only_own_level_profile(self):
        service = _Service()
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_paper_profile(
                LEVEL,
                PaperProfileUpdate(exam_body=" ICAI ", assessment_year="2027"),
                _admin(),
            )

        self.assertEqual(result["profile"]["exam_body"], "ICAI")
        self.assertEqual(result["profile"]["level"], "Foundation")
        own = next(row for row in service.data["paper_profiles"] if row["id"] == "profile-1")
        other = next(row for row in service.data["paper_profiles"] if row["id"] == "other-profile")
        self.assertEqual(own["assessment_year"], "2027")
        self.assertEqual(other["exam_body"], "Private")

    def test_blank_profile_deletes_only_selected_level(self):
        service = _Service()
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_paper_profile(LEVEL, PaperProfileUpdate(), _admin())

        self.assertEqual(result, {"profile": None})
        self.assertEqual([row["id"] for row in service.data["paper_profiles"]], ["other-profile"])

    def test_frontend_default_format_is_still_treated_as_blank(self):
        service = _Service()
        body = PaperProfileUpdate.model_validate({
            "format_config": {
                "sections": [],
                "instructions": [],
                "numbering_style": "numeric",
            }
        })
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_paper_profile(LEVEL, body, _admin())

        self.assertEqual(result, {"profile": None})
        self.assertEqual([row["id"] for row in service.data["paper_profiles"]], ["other-profile"])

    def test_other_tenant_level_is_not_addressable(self):
        service = _Service()
        with patch.object(mod, "get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as error:
                mod.set_paper_profile(
                    "other-tenant-level",
                    PaperProfileUpdate(exam_body="Changed"),
                    _admin(),
                )
        self.assertEqual(error.exception.status_code, 404)

    def test_teacher_cannot_write(self):
        with self.assertRaises(HTTPException) as error:
            mod.set_paper_profile(LEVEL, PaperProfileUpdate(exam_body="ICAI"), _teacher())
        self.assertEqual(error.exception.status_code, 403)

    def test_format_config_is_validated_and_tenant_scoped(self):
        service = _Service()
        body = PaperProfileUpdate.model_validate({
            "exam_body": "ICAI",
            "format_config": {
                "sections": [{"name": "Objective", "question_type": "mcq_single", "count": 20,
                              "min_marks": 1, "max_marks": 2}],
                "duration_minutes": 180,
                "instructions": ["Answer all questions"],
                "numbering_style": "q_numeric",
                "currency_symbol": "₹",
                "locale": "en-IN",
            },
        })
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_paper_profile(LEVEL, body, _admin())
        own = next(row for row in service.data["paper_profiles"] if row["id"] == "profile-1")
        other = next(row for row in service.data["paper_profiles"] if row["id"] == "other-profile")
        self.assertEqual(result["profile"]["format_config"]["duration_minutes"], 180)
        self.assertEqual(own["format_config"]["locale"], "en-IN")
        self.assertNotIn("format_config", other)

    def test_format_config_rejects_inverted_mark_range(self):
        with self.assertRaises(ValueError):
            PaperProfileUpdate.model_validate({
                "format_config": {
                    "sections": [{"name": "Bad", "count": 1, "min_marks": 5, "max_marks": 2}],
                }
            })


if __name__ == "__main__":
    unittest.main()
