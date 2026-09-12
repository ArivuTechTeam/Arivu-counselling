from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.services.llm.base import LLMError
from app.services.map_reduce_prompts import (
    REDUCE_SYSTEM,
    build_reduce_user_prompt,
)
from app.services.master_blueprint_synthesizer import MasterBlueprintSynthesizer

MODULE = "app.services.master_blueprint_synthesizer"


def _topic(name, **kw):
    return {
        "topic_name": name,
        "subtopics": kw.get("subtopics", []),
        "key_definitions": kw.get("key_definitions", []),
        "key_facts_and_figures": kw.get("key_facts_and_figures", []),
        "formulas": kw.get("formulas", []),
        "worked_examples": kw.get("worked_examples", []),
    }


# merged result the (mocked) REDUCE model returns
MERGED = {"topics": [_topic("Strings", subtopics=["indexing", "slicing"])]}


# --- tiny in-memory fake supabase (select/eq/order) -------------------------

class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, []

    def select(self, *_a):
        return self

    def eq(self, k, v):
        self.filters.append((k, v)); return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        out = [dict(r) for r in rows if all(r.get(k) == v for k, v in self.filters)]
        return type("R", (), {"data": out})


class _Fake:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Query(self.db, name)

    def seed(self, document_id, tenant_id, chunks):
        """chunks: list of (chunk_index, map_status, topics_list)."""
        rows = self.db.setdefault("document_chunks", [])
        for idx, status, topics in chunks:
            rows.append(
                {
                    "id": f"{tenant_id}-c{idx}",
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "chunk_index": idx,
                    "map_status": status,
                    "topics_json": {"topics": topics} if topics is not None else None,
                }
            )


class PromptTests(unittest.TestCase):
    def test_reduce_system_states_merge_contract(self) -> None:
        # merges duplicates, drops non-teachable junk, and stays grounded/verbatim
        for token in ("MERGE", "DROP", "VERBATIM", "topics", "Do NOT invent"):
            self.assertIn(token, REDUCE_SYSTEM)

    def test_reduce_user_prompt_carries_topics(self) -> None:
        p = build_reduce_user_prompt(document_title="Doc", topics_json='[{"x":1}]')
        self.assertIn("Doc", p)
        self.assertIn('[{"x":1}]', p)

    def test_reduce_user_prompt_includes_document_summary(self) -> None:
        p = build_reduce_user_prompt(
            document_title="Doc", topics_json="[]", document_summary="About algebra."
        )
        self.assertIn("About algebra.", p)


class SynthesizeTests(unittest.TestCase):
    def test_merges_succeeded_chunks_into_blueprint(self) -> None:
        fake = _Fake()
        fake.seed(
            "d1", "t1",
            [
                (0, "succeeded", [_topic("String basics"), _topic("Indexing")]),
                (1, "succeeded", [_topic("Indexing"), _topic("Slicing")]),  # overlap dup
            ],
        )
        synth = MasterBlueprintSynthesizer(service=fake)

        with patch(
            f"{MODULE}.complete_json_large", return_value=(MERGED, "gemini")
        ) as call:
            bp = synth.synthesize(document_id="d1", tenant_id="t1", document_title="Doc")

        self.assertEqual(bp["document_title"], "Doc")
        self.assertEqual(bp["source_topic_count"], 4)  # 2 + 2 before merge
        self.assertEqual(bp["topics"], MERGED["topics"])
        # REDUCE received all 4 raw topics as its input payload
        _system, user = call.call_args.args
        sent = json.loads(user.split("=== EXTRACTED TOPICS (JSON) ===\n")[1].split("\n=== END")[0])
        self.assertEqual(len(sent), 4)

    def test_ignores_failed_and_queued_chunks(self) -> None:
        fake = _Fake()
        fake.seed(
            "d1", "t1",
            [
                (0, "succeeded", [_topic("Kept")]),
                (1, "failed", None),
                (2, "queued", None),
                (3, "running", None),
            ],
        )
        synth = MasterBlueprintSynthesizer(service=fake)

        with patch(
            f"{MODULE}.complete_json_large", return_value=(MERGED, "gemini")
        ) as call:
            bp = synth.synthesize(document_id="d1", tenant_id="t1")

        self.assertEqual(bp["source_topic_count"], 1)  # only the succeeded chunk
        _system, user = call.call_args.args
        self.assertIn("Kept", user)

    def test_raises_when_nothing_mapped(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "failed", None), (1, "queued", None)])
        synth = MasterBlueprintSynthesizer(service=fake)

        with patch(f"{MODULE}.complete_json_large") as call:
            with self.assertRaises(ValueError):
                synth.synthesize(document_id="d1", tenant_id="t1")
        call.assert_not_called()  # no wasted AI call when there's nothing to merge

    def test_retries_once_then_succeeds(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("A")])])
        synth = MasterBlueprintSynthesizer(service=fake)

        calls = {"n": 0}

        def once_flaky(_s, _u):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMError("transient")
            return (MERGED, "gemini")

        with patch(f"{MODULE}.complete_json_large", side_effect=once_flaky):
            bp = synth.synthesize(document_id="d1", tenant_id="t1")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(bp["topics"], MERGED["topics"])

    def test_reduce_output_is_validated(self) -> None:
        """Junk topics from the model are dropped by the shared validator."""
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("A")])])
        synth = MasterBlueprintSynthesizer(service=fake)

        dirty = {"topics": [{"topic_name": ""}, _topic("Real"), "junk"]}
        with patch(f"{MODULE}.complete_json_large", return_value=(dirty, "gemini")):
            bp = synth.synthesize(document_id="d1", tenant_id="t1")
        self.assertEqual([t["topic_name"] for t in bp["topics"]], ["Real"])

    def test_tenant_scoped(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("Mine")])])
        fake.seed("d1", "OTHER", [(0, "succeeded", [_topic("Theirs")])])
        synth = MasterBlueprintSynthesizer(service=fake)

        with patch(
            f"{MODULE}.complete_json_large", return_value=(MERGED, "gemini")
        ) as call:
            bp = synth.synthesize(document_id="d1", tenant_id="t1")

        self.assertEqual(bp["source_topic_count"], 1)
        _system, user = call.call_args.args
        self.assertIn("Mine", user)
        self.assertNotIn("Theirs", user)


if __name__ == "__main__":
    unittest.main()
