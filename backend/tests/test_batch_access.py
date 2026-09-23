from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.services import batch_access as mod

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
FUTURE_TS = "2027-01-01T00:00:00+00:00"
PAST_TS = "2020-01-01T00:00:00+00:00"
FUTURE_DATE = "2027-01-01"
PAST_DATE = "2020-01-01"


class _Query:
    def __init__(self, service, table):
        self.service = service
        self.table = table
        self.single = False
        self.eqs = []
        self.ins = []
        self._range = None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self.eqs.append((column, value))
        return self

    def in_(self, column, values):
        self.ins.append((column, set(values)))
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, *_a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = [
            row for row in self.service.data.get(self.table, [])
            if all(row.get(c) == v for c, v in self.eqs)
            and all(row.get(c) in vals for c, vals in self.ins)
        ]
        if self.single:
            return SimpleNamespace(data=(rows[0] if rows else None))
        if self._range:
            rows = rows[self._range[0]: self._range[1] + 1]
        return SimpleNamespace(data=list(rows))


class _Service:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


PROFILE = SimpleNamespace(tenant_id="t1", user_id="u1")


class AssignmentAvailableTests(unittest.TestCase):
    def test_active_no_window_is_available(self):
        self.assertTrue(mod.assignment_available({}, NOW))

    def test_withdrawn_is_unavailable(self):
        self.assertFalse(mod.assignment_available({"status": "withdrawn"}, NOW))

    def test_before_start_unavailable(self):
        self.assertFalse(mod.assignment_available({"available_from": FUTURE_TS}, NOW))

    def test_after_end_unavailable(self):
        self.assertFalse(mod.assignment_available({"available_to": PAST_TS}, NOW))

    def test_within_window_available(self):
        self.assertTrue(mod.assignment_available(
            {"available_from": PAST_TS, "available_to": FUTURE_TS}, NOW))


class MembershipActiveTests(unittest.TestCase):
    def test_active_no_dates(self):
        self.assertTrue(mod.membership_active({"active": True}, NOW.date()))

    def test_inactive(self):
        self.assertFalse(mod.membership_active({"active": False}, NOW.date()))

    def test_before_valid_from(self):
        self.assertFalse(mod.membership_active(
            {"active": True, "valid_from": FUTURE_DATE}, NOW.date()))

    def test_after_valid_to(self):
        self.assertFalse(mod.membership_active(
            {"active": True, "valid_to": PAST_DATE}, NOW.date()))


class ActiveBatchIdsTests(unittest.TestCase):
    def test_only_active_in_date_memberships(self):
        service = _Service({"batch_memberships": [
            {"tenant_id": "t1", "profile_id": "u1", "batch_id": "b1", "active": True},
            {"tenant_id": "t1", "profile_id": "u1", "batch_id": "b2", "active": False},
            {"tenant_id": "t1", "profile_id": "u1", "batch_id": "b3", "active": True, "valid_to": PAST_DATE},
        ]})
        self.assertEqual(
            mod.active_batch_ids(service, tenant_id="t1", profile_id="u1", now=NOW),
            {"b1"},
        )


class AssignedQuizIdsTests(unittest.TestCase):
    def _service(self):
        return _Service({
            "batch_memberships": [
                {"tenant_id": "t1", "profile_id": "u1", "batch_id": "b1", "active": True},
            ],
            "quiz_assignments": [
                {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q1", "status": "active"},
                {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q2", "status": "withdrawn"},
                {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q3", "available_to": PAST_TS},
                {"tenant_id": "t1", "batch_id": "bX", "quiz_set_id": "qX", "status": "active"},  # other batch
            ],
        })

    def test_returns_only_available_assignments_for_active_batches(self):
        result = mod.assigned_quiz_ids(self._service(), tenant_id="t1", profile_id="u1", now=NOW)
        self.assertEqual(result, {"q1"})  # q2 withdrawn, q3 expired, qX other batch

    def test_no_memberships_means_no_access(self):
        service = _Service({"batch_memberships": [], "quiz_assignments": [
            {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q1", "status": "active"},
        ]})
        self.assertEqual(
            mod.assigned_quiz_ids(service, tenant_id="t1", profile_id="u1", now=NOW), set())


class StudentCanAccessQuizTests(unittest.TestCase):
    def _quiz(self, audience, status="published"):
        return {"batch_memberships": [], "quiz_assignments": [], "quiz_sets": [
            {"id": "q1", "tenant_id": "t1", "status": status, "subject_id": "s1", "audience_mode": audience},
        ]}

    def _run(self, service, *, batches_enabled, enrolled):
        with patch.object(mod, "get_settings",
                          return_value=SimpleNamespace(batches_enabled=batches_enabled)), \
             patch.object(mod, "enrolled_subject_ids", return_value=enrolled):
            return mod.student_can_access_quiz(service, PROFILE, "q1", now=NOW)

    def test_unpublished_denied(self):
        service = _Service(self._quiz("legacy_course", status="draft"))
        self.assertFalse(self._run(service, batches_enabled=True, enrolled={"s1"}))

    def test_flag_off_uses_legacy_subject_rule(self):
        service = _Service(self._quiz("assigned_batches"))  # audience ignored when flag off
        self.assertTrue(self._run(service, batches_enabled=False, enrolled={"s1"}))
        self.assertFalse(self._run(service, batches_enabled=False, enrolled={"s9"}))

    def test_flag_on_legacy_course_still_subject_rule(self):
        service = _Service(self._quiz("legacy_course"))
        self.assertTrue(self._run(service, batches_enabled=True, enrolled={"s1"}))
        self.assertFalse(self._run(service, batches_enabled=True, enrolled=set()))

    def test_flag_on_assigned_batches_requires_membership_and_assignment(self):
        data = self._quiz("assigned_batches")
        data["batch_memberships"] = [
            {"tenant_id": "t1", "profile_id": "u1", "batch_id": "b1", "active": True}]
        data["quiz_assignments"] = [
            {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q1", "status": "active"}]
        self.assertTrue(self._run(_Service(data), batches_enabled=True, enrolled={"s1"}))

    def test_flag_on_assigned_batches_non_member_denied(self):
        # Enrolled in the subject, but NOT a member of the assigned batch.
        data = self._quiz("assigned_batches")
        data["quiz_assignments"] = [
            {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "q1", "status": "active"}]
        self.assertFalse(self._run(_Service(data), batches_enabled=True, enrolled={"s1"}))


if __name__ == "__main__":
    unittest.main()
