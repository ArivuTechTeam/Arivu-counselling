"""Batch-ON enforcement for the practice/challenge leak guard (P6.1-3).

Proves that with BATCHES_ENABLED on, a question whose only published link is an
`assigned_batches` quiz is released ONLY to that batch's members — while
legacy-course and standalone questions stay available to everyone (unchanged).
This function backs practice selection, challenge creation, and the challenge
take-gate, so covering it covers all three.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import selector as mod

MEMBER = SimpleNamespace(tenant_id="t1", user_id="u_member")
OUTSIDER = SimpleNamespace(tenant_id="t1", user_id="u_outsider")


class _Query:
    def __init__(self, service, table):
        self.service = service
        self.table = table
        self.eqs = []
        self.ins = []
        self._range = None
        self.single = False

    def select(self, *_a, **_k):
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

    def execute(self):
        rows = [
            r for r in self.service.data.get(self.table, [])
            if all(r.get(c) == v for c, v in self.eqs)
            and all(r.get(c) in vals for c, vals in self.ins)
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


def _data():
    # qA -> variant vA -> assigned_batches quiz sA (assigned to batch b1)
    # qL -> variant vL -> legacy_course published quiz sL
    # qS -> standalone (no link)
    return {
        "quiz_variant_questions": [
            {"tenant_id": "t1", "question_id": "qA", "variant_id": "vA", "id": "lA"},
            {"tenant_id": "t1", "question_id": "qL", "variant_id": "vL", "id": "lL"},
        ],
        "quiz_variants": [
            {"tenant_id": "t1", "id": "vA", "quiz_set_id": "sA"},
            {"tenant_id": "t1", "id": "vL", "quiz_set_id": "sL"},
        ],
        "quiz_sets": [
            {"tenant_id": "t1", "id": "sA", "status": "published", "audience_mode": "assigned_batches"},
            {"tenant_id": "t1", "id": "sL", "status": "published", "audience_mode": "legacy_course"},
        ],
        "batch_memberships": [
            {"tenant_id": "t1", "profile_id": "u_member", "batch_id": "b1", "active": True},
        ],
        "quiz_assignments": [
            {"tenant_id": "t1", "batch_id": "b1", "quiz_set_id": "sA", "status": "active"},
        ],
    }


class BatchLeakGuardTests(unittest.TestCase):
    def _released(self, profile):
        with patch.object(mod, "get_settings",
                          return_value=SimpleNamespace(batches_enabled=True)):
            return mod._released_practice_ids(
                _Service(_data()), ["qA", "qL", "qS"], "t1", profile=profile
            )

    def test_member_gets_assigned_legacy_and_standalone(self):
        self.assertEqual(self._released(MEMBER), {"qA", "qL", "qS"})

    def test_outsider_is_denied_assigned_but_keeps_legacy_and_standalone(self):
        # qA (assigned-batch) is withheld from a non-member; qL/qS stay.
        self.assertEqual(self._released(OUTSIDER), {"qL", "qS"})

    def test_flag_off_releases_everything_published(self):
        with patch.object(mod, "get_settings",
                          return_value=SimpleNamespace(batches_enabled=False)):
            released = mod._released_practice_ids(
                _Service(_data()), ["qA", "qL", "qS"], "t1", profile=OUTSIDER
            )
        self.assertEqual(released, {"qA", "qL", "qS"})  # legacy behavior: published = released


if __name__ == "__main__":
    unittest.main()
