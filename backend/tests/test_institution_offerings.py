from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.institution_offerings import (
    institution_offerings_by_tenant,
    offering_counts,
)


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.allowed: set[str] | None = None

    def select(self, *_args):
        return self

    def in_(self, column: str, values: list[str]):
        self.rows = [row for row in self.rows if str(row.get(column)) in values]
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _Service:
    rows = {
        "courses": [
            {"id": "c2", "tenant_id": "t1", "name": "CMA"},
            {"id": "c1", "tenant_id": "t1", "name": "CA"},
            {"id": "other", "tenant_id": "t2", "name": "Other"},
        ],
        "course_levels": [
            {"id": "l2", "tenant_id": "t1", "course_id": "c1", "name": "Final"},
            {"id": "l1", "tenant_id": "t1", "course_id": "c1", "name": "Foundation"},
            {"id": "l3", "tenant_id": "t1", "course_id": "c2", "name": "Foundation"},
        ],
        "subjects": [
            {
                "id": "s2",
                "tenant_id": "t1",
                "course_id": "c1",
                "course_level_id": "l1",
                "name": "Economics",
            },
            {
                "id": "s1",
                "tenant_id": "t1",
                "course_id": "c1",
                "course_level_id": "l1",
                "name": "Accounting",
            },
            {
                "id": "s3",
                "tenant_id": "t1",
                "course_id": "c2",
                "course_level_id": "l3",
                "name": "Business Laws",
            },
        ],
    }

    def table(self, name: str) -> _Query:
        return _Query([dict(row) for row in self.rows[name]])


class InstitutionOfferingsTests(unittest.TestCase):
    def test_builds_sorted_operational_hierarchy_and_counts(self) -> None:
        result = institution_offerings_by_tenant(_Service(), ["t1"])["t1"]

        self.assertEqual([course["name"] for course in result], ["CA", "CMA"])
        self.assertEqual(
            [subject["name"] for subject in result[0]["levels"][1]["subjects"]],
            ["Accounting", "Economics"],
        )
        self.assertEqual(
            offering_counts(result),
            {"course_count": 2, "level_count": 3, "subject_count": 3},
        )


if __name__ == "__main__":
    unittest.main()
