from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api import exam_standards as mod
from app.api.exam_standards import ExamStandardUpdate
from app.lib.auth import CurrentProfile

T = "11111111-1111-1111-1111-111111111111"
COURSE = "22222222-2222-2222-2222-222222222222"
LEVEL = "33333333-3333-3333-3333-333333333333"


def _admin():
    return CurrentProfile(user_id="admin-1", tenant_id=T, role="institution_admin")


def _teacher():
    return CurrentProfile(user_id="t-1", tenant_id=T, role="teacher")


class _Query:
    def __init__(self, service, table):
        self.service, self.table = service, table
        self.eqs, self.op, self.payload, self.single = [], "select", None, False

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

    def in_(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, *_a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = self.service.data.setdefault(self.table, [])
        if self.op == "insert":
            row = {"id": f"new-{self.table}", **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[row])
        matched = [r for r in rows if all(r.get(c) == v for c, v in self.eqs)]
        if self.op == "update":
            for r in matched:
                r.update(self.payload)
            return SimpleNamespace(data=list(matched))
        return SimpleNamespace(data=(matched[0] if matched else None) if self.single else list(matched))


class _Service:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


class PresetsTests(unittest.TestCase):
    def test_lists_presets(self):
        result = mod.list_scoring_presets(_teacher())
        keys = {p["key"] for p in result}
        self.assertIn("ca_foundation", keys)
        self.assertIn("standard", keys)


class SetExamStandardTests(unittest.TestCase):
    def _service(self):
        return _Service({
            "courses": [{"id": COURSE, "tenant_id": T, "name": "CA"}],
            "course_levels": [{"id": LEVEL, "course_id": COURSE, "tenant_id": T, "name": "Foundation"}],
            "scoring_policies": [],
        })

    def test_non_admin_forbidden(self):
        with self.assertRaises(HTTPException) as e:
            mod.set_exam_standard(LEVEL, ExamStandardUpdate(preset_key="ca_foundation"), _teacher())
        self.assertEqual(e.exception.status_code, 403)

    def test_sets_ca_foundation(self):
        service = self._service()
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_exam_standard(LEVEL, ExamStandardUpdate(preset_key="ca_foundation"), _admin())
        self.assertEqual(result["preset_key"], "ca_foundation")
        # a policy was created and linked to the course
        self.assertEqual(len(service.data["scoring_policies"]), 1)
        self.assertEqual(service.data["scoring_policies"][0]["rules"]["wrong_penalty"], 0.25)
        self.assertEqual(service.data["course_levels"][0]["exam_scoring_policy_id"], "new-scoring_policies")

    def test_clear_standard(self):
        service = self._service()
        service.data["course_levels"][0]["exam_scoring_policy_id"] = "some-policy"
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.set_exam_standard(LEVEL, ExamStandardUpdate(preset_key=None), _admin())
        self.assertEqual(result, {"preset_key": None})
        self.assertIsNone(service.data["course_levels"][0]["exam_scoring_policy_id"])

    def test_unknown_preset_400(self):
        service = self._service()
        with patch.object(mod, "get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as e:
                mod.set_exam_standard(LEVEL, ExamStandardUpdate(preset_key="nope"), _admin())
        self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
