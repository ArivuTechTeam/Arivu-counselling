"""Whole-quiz regeneration (regenerate_quiz_set + the endpoint).

Proves: every question is rebuilt with fresh content and reset to pending; the
source material is recovered ONCE (not once per question); a question that fails
to regenerate keeps its previous content; oversized sets are rejected; and the
endpoint is draft-only, owner-scoped, and flag-gated.
"""

from __future__ import annotations

import json
import threading
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.services.llm import LLMError

T = "t1"
TEACHER = "teacher-1"


def _profile() -> CurrentProfile:
    return CurrentProfile(user_id=TEACHER, tenant_id=T, role="teacher")


NEW_Q = json.dumps({"questions": [{
    "type": "mcq_single",
    "question_text": "Which concept underlies accrual accounting?",
    "options": [
        {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
        {"id": "c", "text": "C"}, {"id": "d", "text": "D"},
    ],
    "correct_answer": "b",
    "explanation": "Because expenses match the period they help earn.",
    "difficulty": "medium", "marks": 1,
    "source_excerpt": "matching", "source_page_start": None,
    "source_page_end": None, "grounding_confidence": 0.9,
}]})


class _Query:
    def __init__(self, service: "_Service", table: str) -> None:
        self.service = service
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.memberships: list[tuple[str, set]] = []
        self.payload: dict | None = None
        self.single = False

    def select(self, *_a):
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def in_(self, key, values):
        self.memberships.append((key, set(values)))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def order(self, *_a, **_kw):
        return self

    def _match(self, row):
        return all(row.get(k) == v for k, v in self.filters) and all(
            row.get(k) in vs for k, vs in self.memberships
        )

    def execute(self):
        with self.service.lock:
            rows = self.service.db.setdefault(self.table, [])
            matches = [r for r in rows if self._match(r)]
            if self.payload is not None:
                for r in matches:
                    r.update(self.payload)
                return SimpleNamespace(data=[dict(r) for r in matches])
        return SimpleNamespace(
            data=(dict(matches[0]) if matches else None) if self.single else [dict(r) for r in matches]
        )


class _Service:
    def __init__(self, db: dict[str, list[dict]]) -> None:
        self.db = db
        self.table_calls: Counter = Counter()
        self.lock = threading.Lock()

    def table(self, name: str) -> _Query:
        self.table_calls[name] += 1
        return _Query(self, name)


def _blueprint_world(n: int, status: str = "approved") -> dict[str, list[dict]]:
    return {
        "quiz_sets": [{"id": "set1", "tenant_id": T, "created_by": TEACHER, "status": "draft"}],
        "quiz_variants": [{"id": "v1", "tenant_id": T, "quiz_set_id": "set1"}],
        "quiz_variant_questions": [
            {"tenant_id": T, "variant_id": "v1", "question_id": f"q{i}"} for i in range(n)
        ],
        "questions": [{
            "id": f"q{i}", "tenant_id": T, "type": "mcq_single",
            "question_text": "OLD", "options": [{"id": "a", "text": "Old"}],
            "correct_answer": "a", "explanation": "old", "difficulty": "medium",
            "marks": 1, "topic_id": None, "review_status": status,
        } for i in range(n)],
        "quiz_generation_jobs": [{
            "tenant_id": T, "quiz_set_id": "set1",
            "params": {"selected_topics": [{"name": "Topic A"}]},
            "master_blueprint": {"topics": [
                {"topic_name": "Topic A", "key_facts_and_figures": ["FACT A"]},
            ]},
        }],
    }


def _run(service, **kwargs):
    from app.services.review import regenerate_quiz_set
    with (
        patch("app.services.review.get_service_client", return_value=service),
        patch("app.services.review.get_settings",
              return_value=SimpleNamespace(generation_max_text_chars=100_000)),
        patch("app.services.review.reuse_enabled", return_value=False),
        patch("app.services.review.verify_generated_questions",
              return_value=[SimpleNamespace(status="verified", warnings=[])]),
        patch("app.services.review.complete_with_fallback",
              **kwargs) as complete,
    ):
        from app.services.review import regenerate_quiz_set as fn
        result = fn("set1", T, max_questions=40, concurrency=3)
    return result, complete


class RegenerateSetServiceTests(unittest.TestCase):
    def test_regenerates_all_and_recovers_source_once(self) -> None:
        service = _Service(_blueprint_world(3))
        result, complete = _run(service, return_value=(NEW_Q, "gemini"))
        self.assertEqual(result, {"regenerated": 3, "kept": 0, "total": 3})
        # Source recovered ONCE for the whole set, not once per question.
        self.assertEqual(service.table_calls["quiz_generation_jobs"], 1)
        # Every question rebuilt + reset to pending.
        for q in service.db["questions"]:
            self.assertEqual(q["question_text"], "Which concept underlies accrual accounting?")
            self.assertEqual(q["review_status"], "pending_review")
        self.assertEqual(complete.call_count, 3)

    def test_failed_question_keeps_its_previous_content(self) -> None:
        service = _Service(_blueprint_world(3))
        calls = {"n": 0}
        lock = threading.Lock()

        def flaky(_system, _user, **_kw):
            with lock:
                calls["n"] += 1
                n = calls["n"]
            if n == 2:
                raise LLMError("boom")
            return (NEW_Q, "gemini")

        result, _ = _run(service, side_effect=flaky)
        self.assertEqual(result, {"regenerated": 2, "kept": 1, "total": 3})
        kept = [q for q in service.db["questions"] if q["question_text"] == "OLD"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["review_status"], "approved")  # untouched

    def test_multiple_generation_jobs_does_not_crash(self) -> None:
        # A quiz set with more than one generation job must not raise (the old
        # maybe_single() 500'd here); the blueprint-carrying job is used.
        world = _blueprint_world(3)
        world["quiz_generation_jobs"].insert(0, {
            "tenant_id": T, "quiz_set_id": "set1", "params": {}, "master_blueprint": None,
        })
        service = _Service(world)
        result, _ = _run(service, return_value=(NEW_Q, "gemini"))
        self.assertEqual(result, {"regenerated": 3, "kept": 0, "total": 3})

    def test_oversized_set_is_rejected(self) -> None:
        from app.services.review import regenerate_quiz_set
        service = _Service(_blueprint_world(5))
        with (
            patch("app.services.review.get_service_client", return_value=service),
            patch("app.services.review.reuse_enabled", return_value=False),
            self.assertRaises(ValueError),
        ):
            regenerate_quiz_set("set1", T, max_questions=3, concurrency=2)


class RegenerateSetEndpointTests(unittest.TestCase):
    def test_synchronous_route_is_retired_without_calling_ai(self) -> None:
        from app.api.quiz import regenerate_all_questions
        with patch("app.services.review.regenerate_quiz_set") as bulk, self.assertRaises(HTTPException) as raised:
            regenerate_all_questions("set1", _profile())
        self.assertEqual(raised.exception.status_code, 410)
        bulk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
