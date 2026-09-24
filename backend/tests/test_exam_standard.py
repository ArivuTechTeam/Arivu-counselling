from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.api import practice as mod
from app.lib.auth import CurrentProfile

T = "tenant-1"
COURSE = "course-1"
LEVEL = "level-1"
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

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
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
        "tenants": [{"id": T, "exam_config": {"questions": 50, "duration_minutes": 60, "negative_marking": 0.25}}],
        "enrollments": [{"tenant_id": T, "profile_id": "stu-1", "course_id": COURSE, "course_level_id": LEVEL}],
        "course_levels": [{"tenant_id": T, "id": LEVEL, "course_id": COURSE, "exam_scoring_policy_id": policy_on_course}],
        "scoring_policies": [{"tenant_id": T, "id": POLICY, "rules": rules or {"wrong_penalty": 0.25}}],
    })


def _service_with_conflicting_levels():
    service = _service()
    service.data["enrollments"].append({
        "tenant_id": T,
        "profile_id": "stu-1",
        "course_id": "course-2",
        "course_level_id": "level-2",
    })
    service.data["course_levels"].append({
        "tenant_id": T,
        "id": "level-2",
        "course_id": "course-2",
        "exam_scoring_policy_id": "policy-2",
    })
    service.data["scoring_policies"].append({
        "tenant_id": T,
        "id": "policy-2",
        "rules": {"wrong_penalty": 0},
    })
    return service


class ResolveExamScoringPolicyTests(unittest.TestCase):
    def _resolve(self, service, *, enabled):
        with patch.object(mod, "get_settings",
                          return_value=SimpleNamespace(scoring_policies_enabled=enabled)):
            return mod._resolve_exam_scoring_policy(service, STUDENT)

    def test_disabled_returns_none(self):
        self.assertIsNone(self._resolve(_service(), enabled=False))

    def test_enabled_returns_course_level_policy_rules(self):
        self.assertEqual(self._resolve(_service(), enabled=True), {"wrong_penalty": 0.25})

    def test_no_policy_on_course_level_returns_none(self):
        self.assertIsNone(self._resolve(_service(policy_on_course=None), enabled=True))

    def test_conflicting_enrolled_level_policies_do_not_pick_arbitrarily(self):
        self.assertIsNone(self._resolve(_service_with_conflicting_levels(), enabled=True))

    def test_exam_briefing_uses_effective_course_policy(self):
        service = _service(rules={
            "wrong_penalty": 0.5,
            "penalty_is_fraction": True,
            "multi_mode": "mrm_partial",
        })
        with patch.object(mod, "get_service_client", return_value=service), patch.object(
            mod, "get_settings", return_value=SimpleNamespace(scoring_policies_enabled=True)
        ):
            briefing = mod.exam_config(STUDENT)
        self.assertEqual(briefing["negative_marking"], 0.5)
        self.assertTrue(briefing["penalty_is_fraction"])
        self.assertTrue(briefing["partial_credit"])
        self.assertIsNone(briefing["active_session_id"])

    def test_active_exam_briefing_keeps_frozen_pattern_and_policy(self):
        service = _service(rules={"wrong_penalty": 0.5})
        service.data["practice_sessions"] = [{
            "id": "exam-1", "tenant_id": T, "student_id": STUDENT.user_id,
            "mode": "exam", "status": "in_progress", "started_at": "2026-09-24T00:00:00Z",
            "config": {"count": 20, "duration_minutes": 30, "negative_marking": 0.25},
            "scoring_policy_snapshot": {"wrong_penalty": 0.1},
        }]
        with patch.object(mod, "get_service_client", return_value=service), patch.object(
            mod, "get_settings", return_value=SimpleNamespace(scoring_policies_enabled=True)
        ):
            briefing = mod.exam_config(STUDENT)
        self.assertEqual(briefing["active_session_id"], "exam-1")
        self.assertEqual(briefing["questions"], 20)
        self.assertEqual(briefing["duration_minutes"], 30)
        self.assertEqual(briefing["negative_marking"], 0.1)
        self.assertFalse(briefing["penalty_is_fraction"])

    def test_exam_briefing_falls_back_to_institution_penalty(self):
        with patch.object(mod, "get_service_client", return_value=_service()), patch.object(
            mod, "get_settings", return_value=SimpleNamespace(scoring_policies_enabled=False)
        ):
            briefing = mod.exam_config(STUDENT)
        self.assertEqual(briefing["negative_marking"], 0.25)
        self.assertFalse(briefing["penalty_is_fraction"])


if __name__ == "__main__":
    unittest.main()
