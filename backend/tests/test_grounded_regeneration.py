from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.review import regenerate_question


class _Query:
    def __init__(self, db: dict[str, list[dict]], table: str) -> None:
        self.db = db
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.payload: dict | None = None
        self.single = False

    def select(self, *_args):
        return self

    def update(self, payload: dict):
        self.payload = payload
        return self

    def eq(self, key: str, value: object):
        self.filters.append((key, value))
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        matches = [row for row in rows if all(row.get(k) == v for k, v in self.filters)]
        if self.payload is not None:
            for row in matches:
                row.update(self.payload)
            return SimpleNamespace(data=[dict(row) for row in matches])
        return SimpleNamespace(
            data=(dict(matches[0]) if matches else None) if self.single else [dict(r) for r in matches]
        )


class _Service:
    def __init__(self, db: dict[str, list[dict]]) -> None:
        self.db = db

    def table(self, name: str) -> _Query:
        return _Query(self.db, name)


class GroundedRegenerationTests(unittest.TestCase):
    def test_large_document_regeneration_receives_exact_selected_topic_material(self) -> None:
        service = _Service({
            "questions": [{
                "id": "q1", "tenant_id": "t1", "topic_id": "topic-late",
                "type": "mcq_single", "question_text": "Old question?",
                "options": [{"id": "a", "text": "Old A"}],
                "correct_answer": "a", "explanation": "Old explanation",
                "difficulty": "medium", "marks": 1,
            }],
            "quiz_variant_questions": [{
                "tenant_id": "t1", "question_id": "q1", "variant_id": "v1",
            }],
            "quiz_variants": [{
                "id": "v1", "tenant_id": "t1", "quiz_set_id": "set1",
            }],
            "quiz_generation_jobs": [{
                "tenant_id": "t1", "quiz_set_id": "set1",
                "params": {"selected_topics": [{"name": "Late topic", "weight": "high"}]},
                "master_blueprint": {"topics": [
                    {"topic_name": "Early topic", "key_facts_and_figures": ["EARLY FACT"]},
                    {"topic_name": "Late topic", "key_facts_and_figures": ["PAGE 95 FACT"]},
                ]},
            }],
        })
        regenerated = json.dumps({"questions": [{
            "type": "mcq_single", "question_text": "New grounded question?",
            "options": [
                {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
                {"id": "c", "text": "C"}, {"id": "d", "text": "D"},
            ],
            "correct_answer": "b", "explanation": "Because PAGE 95 FACT",
            "difficulty": "medium", "marks": 1,
            "source_excerpt": "PAGE 95 FACT",
            "source_page_start": None,
            "source_page_end": None,
            "grounding_confidence": 0.9,
        }]})

        with patch("app.services.review.get_service_client", return_value=service), patch(
            "app.services.review.get_settings",
            return_value=SimpleNamespace(generation_max_text_chars=100_000),
        ), patch(
            "app.services.review.complete_with_fallback", return_value=(regenerated, "gemini")
        ) as complete, patch(
            "app.services.review.verify_generated_questions",
            return_value=[SimpleNamespace(status="verified", warnings=[])],
        ):
            result = regenerate_question("q1", "t1")

        prompt = complete.call_args.args[1]
        self.assertIn("PAGE 95 FACT", prompt)
        self.assertNotIn("EARLY FACT", prompt)
        self.assertIn("ORIGINAL SOURCE MATERIAL", prompt)
        self.assertEqual(result["question_text"], "New grounded question?")
        self.assertEqual(service.db["questions"][0]["review_status"], "pending_review")


if __name__ == "__main__":
    unittest.main()
