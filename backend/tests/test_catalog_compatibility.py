from __future__ import annotations

import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException

from app.api.academics import _catalog_tenant
from app.lib.auth import CurrentProfile
from app.services.catalog import catalog_tree, provision_catalog_subject


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_MIGRATION = ROOT / "migrations" / "migration-45-global-course-catalog.sql"
SEED_MIGRATION = ROOT / "migrations" / "migration-46-seed-global-course-catalog.sql"


class _Rpc:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _ProvisionService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name: str, params: dict) -> _Rpc:
        self.calls.append((name, params))
        return _Rpc(self.rows)


class _TableQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def order(self, _column: str, **_kwargs):
        return self

    def execute(self):
        rows = self.rows
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        return SimpleNamespace(data=[dict(row) for row in rows])


class _CatalogService:
    def __init__(self) -> None:
        self.tables = {
            "catalog_courses": [
                {"id": "course-1", "code": "CA", "name": "Chartered Accountant", "display_order": 0, "is_active": True},
            ],
            "catalog_course_levels": [
                {"id": "level-1", "catalog_course_id": "course-1", "name": "Foundation", "display_order": 0, "is_active": True},
            ],
            "catalog_course_subjects": [
                {"id": "subject-1", "catalog_level_id": "level-1", "name": "Accounting", "is_active": True},
                {"id": "subject-2", "catalog_level_id": "level-1", "name": "Business Laws", "is_active": True},
            ],
            "institution_offerings": [
                {"tenant_id": "tenant-a", "catalog_subject_id": "subject-1"},
                {"tenant_id": "tenant-b", "catalog_subject_id": "subject-2"},
            ],
        }

    def table(self, name: str) -> _TableQuery:
        return _TableQuery(self.tables[name])


class CatalogSeedMigrationTests(unittest.TestCase):
    def test_seed_contains_exact_expected_hierarchy(self) -> None:
        sql = SEED_MIGRATION.read_text(encoding="utf-8")
        seed = sql.split("$catalog$", 2)[1]
        rows = [
            tuple(part.strip() for part in line.split("|"))
            for line in seed.strip().splitlines()
        ]

        self.assertEqual(len(rows), 175)
        self.assertTrue(all(len(row) == 3 for row in rows))
        self.assertEqual(len({row[0] for row in rows}), 12)
        self.assertEqual(len({row[:2] for row in rows}), 34)
        self.assertEqual(len(set(rows)), 175)

    def test_seed_has_runtime_count_guard(self) -> None:
        sql = SEED_MIGRATION.read_text(encoding="utf-8").lower()
        self.assertIn("seeded_courses <> 12", sql)
        self.assertIn("seeded_levels <> 34", sql)
        self.assertIn("seeded_subjects <> 175", sql)


class CatalogSchemaSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = SCHEMA_MIGRATION.read_text(encoding="utf-8").lower()

    def test_catalog_reads_are_authenticated_and_writes_are_super_admin_only(self) -> None:
        for table in (
            "catalog_courses",
            "catalog_course_levels",
            "catalog_course_subjects",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", self.sql)
        self.assertIn("for select to authenticated using (true)", self.sql)
        self.assertNotRegex(
            self.sql,
            re.compile(r"catalog_(?:courses|course_levels|course_subjects).*to anon", re.DOTALL),
        )
        self.assertIn("with check ((select public.is_super_admin()))", self.sql)

    def test_offerings_are_unique_and_tenant_isolated(self) -> None:
        self.assertIn("unique (tenant_id, catalog_subject_id)", self.sql)
        self.assertIn(
            "tenant_id = (select public.current_tenant_id())",
            self.sql,
        )
        self.assertIn(
            'create policy "tenant members read institution offerings"',
            self.sql,
        )

    def test_provisioning_is_service_only_idempotent_and_collision_safe(self) -> None:
        self.assertIn(
            "revoke all on function public.provision_catalog_subject(uuid, uuid)",
            self.sql,
        )
        self.assertIn(
            "grant execute on function public.provision_catalog_subject(uuid, uuid)\n  to service_role",
            self.sql,
        )
        self.assertGreaterEqual(self.sql.count("on conflict (tenant_id, catalog_subject_id)"), 2)
        self.assertIn("where catalog_course_id is null", self.sql)
        self.assertIn("where catalog_subject_id is null", self.sql)
        self.assertIn("raise log 'catalog provisioning kept same-name free-form rows separate", self.sql)


class ProvisionCatalogSubjectTests(unittest.TestCase):
    def test_first_and_repeated_calls_return_the_same_linked_rows(self) -> None:
        rows = [
            {
                "course_id": "tenant-course-1",
                "subject_id": "tenant-subject-1",
                "course_name_collision": False,
                "subject_name_collision": False,
            }
        ]
        service = _ProvisionService(rows)

        first = provision_catalog_subject(
            service,
            tenant_id="tenant-1",
            catalog_subject_id="catalog-subject-1",
        )
        second = provision_catalog_subject(
            service,
            tenant_id="tenant-1",
            catalog_subject_id="catalog-subject-1",
        )

        self.assertEqual(first.course_id, "tenant-course-1")
        self.assertEqual(first.subject_id, "tenant-subject-1")
        self.assertEqual(second, first)
        self.assertEqual(len(service.calls), 2)
        self.assertTrue(
            all(call[0] == "provision_catalog_subject" for call in service.calls)
        )

    def test_name_collision_is_reported_without_merging(self) -> None:
        service = _ProvisionService(
            [
                {
                    "course_id": "catalog-linked-course",
                    "subject_id": "catalog-linked-subject",
                    "course_name_collision": True,
                    "subject_name_collision": True,
                }
            ]
        )

        with self.assertLogs("app.services.catalog", level="WARNING"):
            result = provision_catalog_subject(
                service,
                tenant_id="tenant-1",
                catalog_subject_id="catalog-subject-1",
            )

        self.assertEqual(result.course_id, "catalog-linked-course")
        self.assertEqual(result.subject_id, "catalog-linked-subject")
        self.assertTrue(result.course_name_collision)
        self.assertTrue(result.subject_name_collision)


class CatalogReadAndAuthorizationTests(unittest.TestCase):
    def test_catalog_tree_marks_only_the_target_tenants_offerings(self) -> None:
        tree = catalog_tree(_CatalogService(), "tenant-a")

        subjects = tree[0]["levels"][0]["subjects"]
        self.assertEqual(
            [(subject["id"], subject["offered"]) for subject in subjects],
            [("subject-1", True), ("subject-2", False)],
        )

    def test_institution_admin_cannot_target_another_tenant(self) -> None:
        profile = CurrentProfile(
            user_id="admin-a",
            tenant_id="00000000-0000-4000-8000-000000000001",
            role="institution_admin",
        )
        with self.assertRaises(HTTPException) as caught:
            _catalog_tenant(
                profile,
                UUID("00000000-0000-4000-8000-000000000002"),
                required=True,
            )
        self.assertEqual(caught.exception.status_code, 403)

    def test_super_admin_must_name_a_tenant_when_provisioning(self) -> None:
        profile = CurrentProfile(
            user_id="super-a",
            tenant_id="00000000-0000-4000-8000-000000000001",
            role="super_admin",
        )
        with self.assertRaises(HTTPException) as caught:
            _catalog_tenant(profile, None, required=True)
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
