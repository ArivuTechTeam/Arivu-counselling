from __future__ import annotations

from types import SimpleNamespace

from app.lib.auth import CurrentProfile
from app.services.selector import enrolled_subject_ids


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.values: tuple[str, set[object]] | None = None

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[object]):
        self.values = (column, set(values))
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        if self.values:
            column, values = self.values
            rows = [row for row in rows if row.get(column) in values]
        return SimpleNamespace(data=rows)


class _Service:
    def __init__(self) -> None:
        self.tables = {
            "enrollments": [
                {
                    "tenant_id": "tenant-a",
                    "profile_id": "student-a",
                    "course_id": "course-a",
                    "course_level_id": "foundation",
                }
            ],
            "subjects": [
                {"id": "accounting", "tenant_id": "tenant-a", "course_id": "course-a", "course_level_id": "foundation"},
                {"id": "audit", "tenant_id": "tenant-a", "course_id": "course-a", "course_level_id": "final"},
                {"id": "other-tenant", "tenant_id": "tenant-b", "course_id": "course-a", "course_level_id": "foundation"},
            ],
        }

    def table(self, name: str):
        return _Query(self.tables[name])


def test_student_only_receives_subjects_from_enrolled_level() -> None:
    profile = CurrentProfile(
        user_id="student-a", tenant_id="tenant-a", role="student"
    )

    assert enrolled_subject_ids(_Service(), profile) == {"accounting"}


def test_legacy_course_only_enrollment_keeps_previous_visibility() -> None:
    service = _Service()
    service.tables["enrollments"][0]["course_level_id"] = None
    profile = CurrentProfile(
        user_id="student-a", tenant_id="tenant-a", role="student"
    )

    assert enrolled_subject_ids(service, profile) == {"accounting", "audit"}
