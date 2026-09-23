from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api import batches as mod
from app.api.batches import BatchCreate, MemberAdd
from app.lib.auth import CurrentProfile

TENANT = "11111111-1111-1111-1111-111111111111"
COURSE = "22222222-2222-2222-2222-222222222222"
BATCH = "33333333-3333-3333-3333-333333333333"
STUDENT = "44444444-4444-4444-4444-444444444444"


def _admin():
    return CurrentProfile(user_id="admin-1", tenant_id=TENANT, role="institution_admin")


def _teacher():
    return CurrentProfile(user_id="teach-1", tenant_id=TENANT, role="teacher")


class _Query:
    def __init__(self, service, table):
        self.service = service
        self.table = table
        self.eqs = []
        self.ins = []
        self.op = "select"
        self.payload = None
        self.single = False

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, c, v):
        self.eqs.append((c, v))
        return self

    def in_(self, c, values):
        self.ins.append((c, set(values)))
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def _match(self, row):
        return (
            all(row.get(c) == v for c, v in self.eqs if "." not in c)
            and all(row.get(c) in vals for c, vals in self.ins)
        )

    def execute(self):
        rows = self.service.data.setdefault(self.table, [])
        if self.op == "insert":
            row = {"id": f"new-{self.table}", **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[row])
        if self.op == "update":
            matched = [r for r in rows if self._match(r)]
            for r in matched:
                r.update(self.payload)
            return SimpleNamespace(data=list(matched))
        matched = [r for r in rows if self._match(r)]
        if self.single:
            return SimpleNamespace(data=(matched[0] if matched else None))
        return SimpleNamespace(data=list(matched))


class _Service:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


class PublicBatchesTests(unittest.TestCase):
    def test_returns_active_batches_for_course(self):
        service = _Service({"batches": [
            {"id": BATCH, "name": "CA 2026", "tenant_id": TENANT, "course_id": COURSE, "status": "active"},
            {"id": "b2", "name": "Archived", "tenant_id": TENANT, "course_id": COURSE, "status": "archived"},
        ]})
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.public_batches(TENANT, COURSE)
        self.assertEqual(result, [{"id": BATCH, "name": "CA 2026"}])


class CreateBatchTests(unittest.TestCase):
    def test_teacher_forbidden(self):
        with self.assertRaises(HTTPException) as e:
            mod.create_batch(BatchCreate(course_id=COURSE, name="X"), _teacher())
        self.assertEqual(e.exception.status_code, 403)

    def test_admin_creates_when_course_exists(self):
        service = _Service({"courses": [{"id": COURSE, "tenant_id": TENANT}], "batches": []})
        with patch.object(mod, "get_service_client", return_value=service):
            row = mod.create_batch(BatchCreate(course_id=COURSE, name=" CA 2026 "), _admin())
        self.assertEqual(row["name"], "CA 2026")
        self.assertEqual(row["tenant_id"], TENANT)

    def test_unknown_course_404(self):
        service = _Service({"courses": [], "batches": []})
        with patch.object(mod, "get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as e:
                mod.create_batch(BatchCreate(course_id=COURSE, name="X"), _admin())
        self.assertEqual(e.exception.status_code, 404)


class MemberManagementTests(unittest.TestCase):
    def _service(self, memberships=None):
        return _Service({
            "batches": [{"id": BATCH, "tenant_id": TENANT, "course_id": COURSE, "name": "B", "status": "active"}],
            "profiles": [{"id": STUDENT, "tenant_id": TENANT, "role": "student"}],
            "batch_memberships": memberships if memberships is not None else [],
        })

    def test_add_member_inserts_for_new_student(self):
        service = self._service()
        with patch.object(mod, "get_service_client", return_value=service):
            mod.add_member(BATCH, MemberAdd(profile_id=STUDENT), _admin())
        self.assertEqual(len(service.data["batch_memberships"]), 1)
        self.assertEqual(service.data["batch_memberships"][0]["membership_role"], "student")

    def test_add_member_restores_existing(self):
        service = self._service(memberships=[
            {"id": "m1", "tenant_id": TENANT, "batch_id": BATCH, "profile_id": STUDENT, "active": False}])
        with patch.object(mod, "get_service_client", return_value=service):
            mod.add_member(BATCH, MemberAdd(profile_id=STUDENT), _admin())
        self.assertTrue(service.data["batch_memberships"][0]["active"])

    def test_add_non_student_rejected(self):
        service = _Service({
            "batches": [{"id": BATCH, "tenant_id": TENANT, "course_id": COURSE, "name": "B", "status": "active"}],
            "profiles": [{"id": STUDENT, "tenant_id": TENANT, "role": "teacher"}],
            "batch_memberships": [],
        })
        with patch.object(mod, "get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as e:
                mod.add_member(BATCH, MemberAdd(profile_id=STUDENT), _admin())
        self.assertEqual(e.exception.status_code, 404)

    def test_deactivate_member(self):
        service = self._service(memberships=[
            {"id": "m1", "tenant_id": TENANT, "batch_id": BATCH, "profile_id": STUDENT, "active": True}])
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.deactivate_member(BATCH, STUDENT, _admin())
        self.assertEqual(result, {"deactivated": True})
        self.assertFalse(service.data["batch_memberships"][0]["active"])


if __name__ == "__main__":
    unittest.main()
