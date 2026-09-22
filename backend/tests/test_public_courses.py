from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID

from app.api.academics import public_courses


class _Result:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.operations: list[tuple] = []

    def select(self, columns: str) -> "_Query":
        self.operations.append(("select", columns))
        return self

    def eq(self, column: str, value: object) -> "_Query":
        self.operations.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[object]) -> "_Query":
        self.operations.append(("in", column, values))
        self.rows = [row for row in self.rows if row.get(column) in values]
        return self

    def order(self, column: str, **_kwargs) -> "_Query":
        self.operations.append(("order", column))
        return self

    def execute(self) -> _Result:
        return _Result(self.rows)


class _Service:
    def __init__(self, queries: dict[str, _Query]) -> None:
        self.queries = queries

    def table(self, name: str) -> _Query:
        query = self.queries[name]
        query.operations.append(("table", name))
        return query


class PublicCoursesTests(unittest.TestCase):
    def test_requires_active_tenant_and_hides_join_metadata(self) -> None:
        tenant_id = UUID("00000000-0000-4000-8000-000000000001")
        query = _Query(
            [
                {
                    "id": "course-1",
                    "name": "Science",
                    "tenants": {"is_active": True},
                }
            ]
        )
        levels_query = _Query(
            [
                {
                    "id": "level-1",
                    "course_id": "course-1",
                    "name": "Foundation",
                    "tenant_id": str(tenant_id),
                    "is_active": True,
                }
            ]
        )

        with patch(
            "app.api.academics.get_service_client",
            return_value=_Service(
                {"courses": query, "course_levels": levels_query}
            ),
        ):
            result = public_courses(tenant_id)

        self.assertEqual(
            result,
            [
                {
                    "id": "course-1",
                    "name": "Science",
                    "levels": [{"id": "level-1", "name": "Foundation"}],
                }
            ],
        )
        self.assertIn(
            ("select", "id, name, tenants!inner(is_active)"),
            query.operations,
        )
        self.assertIn(("eq", "tenant_id", str(tenant_id)), query.operations)
        self.assertIn(("eq", "tenants.is_active", True), query.operations)


if __name__ == "__main__":
    unittest.main()
