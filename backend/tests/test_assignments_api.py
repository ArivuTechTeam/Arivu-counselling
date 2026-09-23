from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api import assignments as mod
from app.api.assignments import AssignRequest
from app.lib.auth import CurrentProfile

T = "11111111-1111-1111-1111-111111111111"
QUIZ = "22222222-2222-2222-2222-222222222222"
SUBJECT = "33333333-3333-3333-3333-333333333333"
COURSE = "44444444-4444-4444-4444-444444444444"
LEVEL = "77777777-7777-7777-7777-777777777777"
BATCH = "55555555-5555-5555-5555-555555555555"
OTHER_BATCH = "66666666-6666-6666-6666-666666666666"


def _teacher():
    return CurrentProfile(user_id="teacher-1", tenant_id=T, role="teacher")


class _Query:
    def __init__(self, service, table):
        self.service, self.table = service, table
        self.eqs, self.ins = [], []
        self.op, self.payload, self.single, self._range = "select", None, False, None

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

    def range(self, s, e):
        self._range = (s, e)
        return self

    def limit(self, *_a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def _match(self, r):
        return (all(r.get(c) == v for c, v in self.eqs if "." not in c)
                and all(r.get(c) in vals for c, vals in self.ins))

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
        if self._range:
            matched = matched[self._range[0]: self._range[1] + 1]
        return SimpleNamespace(data=list(matched))


class _Service:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


def _base(status="published"):
    return {
        "quiz_sets": [{"id": QUIZ, "tenant_id": T, "created_by": "teacher-1",
                       "status": status, "subject_id": SUBJECT, "audience_mode": "legacy_course"}],
        "subjects": [{"id": SUBJECT, "tenant_id": T, "course_id": COURSE, "course_level_id": LEVEL}],
        "batches": [{"id": BATCH, "tenant_id": T, "course_id": COURSE, "course_level_id": LEVEL, "status": "active"},
                    {"id": OTHER_BATCH, "tenant_id": T, "course_id": "other-course", "course_level_id": LEVEL, "status": "active"}],
        "quiz_assignments": [],
    }


def _assign(service, batch_ids, *, enabled=True):
    with patch.object(mod, "get_settings", return_value=SimpleNamespace(batches_enabled=enabled)), \
         patch.object(mod, "get_service_client", return_value=service):
        return mod.assign_to_batches(QUIZ, AssignRequest(batch_ids=batch_ids), _teacher())


class AssignTests(unittest.TestCase):
    def test_flag_off_is_503(self):
        with self.assertRaises(HTTPException) as e:
            _assign(_Service(_base()), [BATCH], enabled=False)
        self.assertEqual(e.exception.status_code, 503)

    def test_non_teacher_forbidden(self):
        with patch.object(mod, "get_settings", return_value=SimpleNamespace(batches_enabled=True)):
            with self.assertRaises(HTTPException) as e:
                mod.assign_to_batches(
                    QUIZ, AssignRequest(batch_ids=[BATCH]),
                    CurrentProfile(user_id="s", tenant_id=T, role="student"))
        self.assertEqual(e.exception.status_code, 403)

    def test_unpublished_rejected(self):
        with self.assertRaises(HTTPException) as e:
            _assign(_Service(_base(status="draft")), [BATCH])
        self.assertEqual(e.exception.status_code, 400)

    def test_batch_from_other_course_rejected(self):
        with self.assertRaises(HTTPException) as e:
            _assign(_Service(_base()), [OTHER_BATCH])
        self.assertEqual(e.exception.status_code, 400)

    def test_assign_flips_audience_and_creates_assignment(self):
        service = _Service(_base())
        result = _assign(service, [BATCH])
        self.assertEqual(result["audience_mode"], "assigned_batches")
        self.assertEqual(len(service.data["quiz_assignments"]), 1)
        self.assertEqual(service.data["quiz_sets"][0]["audience_mode"], "assigned_batches")

    def test_assign_is_idempotent(self):
        service = _Service(_base())
        _assign(service, [BATCH])
        _assign(service, [BATCH])  # same pair again
        self.assertEqual(len(service.data["quiz_assignments"]), 1)  # updated, not duplicated

    def test_withdraw_sets_status(self):
        service = _Service(_base())
        service.data["quiz_assignments"] = [
            {"id": "a1", "tenant_id": T, "quiz_set_id": QUIZ, "batch_id": BATCH, "status": "active"}]
        with patch.object(mod, "get_service_client", return_value=service):
            result = mod.withdraw_assignment(QUIZ, BATCH, _teacher())
        self.assertEqual(result, {"withdrawn": True})
        self.assertEqual(service.data["quiz_assignments"][0]["status"], "withdrawn")


if __name__ == "__main__":
    unittest.main()
