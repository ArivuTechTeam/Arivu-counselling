from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api import practice as mod
from app.lib.auth import CurrentProfile

T = "tenant-1"
COURSE = "course-1"
POLICY = "policy-1"
STUDENT = CurrentProfile(user_id="stu-1", tenant_id=T, role="student")


class _Query:
    def __init__(self, service, table):
        self.service, self.table = service, table
        self.eqs, self.ins, self.single = [], [], False

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.eqs.append((c, v))
        return self

    def in_(self, c, values):
        self.ins.append((c, set(values)))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = [
            r for r in self.service.data.get(self.table, [])
            if all(r.get(c) == v for c, v in self.eqs)
            and all(r.get(c) in vals for c, vals in self.ins)
        ]
        return SimpleNamespace(data=(rows[0] if rows else None) if self.single else rows)


class _Service:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return _Query(self, name)


def _service(policy_on_course=POLICY, rules=None):
    return _Service({
        "enrollments": [{"tenant_id": T, "profile_id": "stu-1", "course_id": COURSE}],
        "courses": [{"tenant_id": T, "id": COURSE, "exam_scoring_policy_id": policy_on_course}],
        "scoring_policies": [{"tenant_id": T, "id": POLICY, "rules": rules or {"wrong_penalty": 0.25}}],
    })


class ResolveExamScoringPolicyTests(unittest.TestCase):
    def _resolve(self, service, *, enabled):
        with patch.object(mod, "get_settings",
                          return_value=SimpleNamespace(scoring_policies_enabled=enabled)):
            return mod._resolve_exam_scoring_policy(service, STUDENT)

    def test_disabled_returns_none(self):
        self.assertIsNone(self._resolve(_service(), enabled=False))

    def test_enabled_returns_course_policy_rules(self):
        self.assertEqual(self._resolve(_service(), enabled=True), {"wrong_penalty": 0.25})

    def test_no_policy_on_course_returns_none(self):
        self.assertIsNone(self._resolve(_service(policy_on_course=None), enabled=True))


if __name__ == "__main__":
    unittest.main()
