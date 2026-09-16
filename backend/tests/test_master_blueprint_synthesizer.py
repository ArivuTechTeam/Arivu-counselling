from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.lib.auth import CurrentProfile
from app.services.llm.base import LLMError
from app.services.map_reduce_prompts import (
    REDUCE_SYSTEM,
    build_reduce_user_prompt,
)
from app.services.master_blueprint_synthesizer import (
    MasterBlueprintSynthesizer,
    apply_merge_plan,
    build_topic_catalogue,
    keep_verified_source_excerpts,
    spot_check_verbatim_facts,
)

MODULE = "app.services.master_blueprint_synthesizer"


def _topic(name, **kw):
    return {
        "topic_name": name,
        "subtopics": kw.get("subtopics", []),
        "key_definitions": kw.get("key_definitions", []),
        "key_facts_and_figures": kw.get("key_facts_and_figures", []),
        "formulas": kw.get("formulas", []),
        "worked_examples": kw.get("worked_examples", []),
        "source_page_ranges": kw.get("source_page_ranges", []),
    }


# compact plan the (mocked) REDUCE model returns
MERGE_PLAN = {
    "topic_groups": [{"topic_name": "Strings", "source_topic_ids": ["T0001"]}],
    "discarded_source_topic_ids": [],
}


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
                    "content": "Python strings support indexing and slicing operations.",
                    "page_start": idx * 10 + 1,
                    "page_end": idx * 10 + 12,
                }
            )


class PromptTests(unittest.TestCase):
    def test_reduce_system_states_merge_contract(self) -> None:
        # merges duplicates, drops non-teachable junk, and stays grounded/verbatim
        for token in ("MERGE", "DROP", "source_topic_ids", "merge PLAN", "Never invent"):
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
            f"{MODULE}.complete_json_large", return_value=(MERGE_PLAN, "gemini")
        ) as call:
            bp = synth.synthesize(document_id="d1", tenant_id="t1", document_title="Doc")

        self.assertEqual(bp["document_title"], "Doc")
        self.assertEqual(bp["source_topic_count"], 4)  # 2 + 2 before merge
        self.assertEqual(len(bp["topics"]), 4)  # omitted ids are safely retained
        self.assertEqual(bp["topics"][0]["topic_name"], "Strings")
        self.assertEqual(bp["verbatim_spot_check"]["checked"], 0)
        # REDUCE received a compact catalogue, not the large verbatim payload.
        _system, user = call.call_args.args
        sent = json.loads(user.split("=== TOPIC CATALOGUE (JSON) ===\n")[1].split("\n=== END")[0])
        self.assertEqual(len(sent), 4)
        self.assertEqual(sent[0]["source_topic_id"], "T0001")
        self.assertNotIn("key_facts_and_figures", sent[0])

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
            f"{MODULE}.complete_json_large", return_value=(MERGE_PLAN, "gemini")
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
            return (MERGE_PLAN, "gemini")

        with patch(f"{MODULE}.complete_json_large", side_effect=once_flaky):
            bp = synth.synthesize(document_id="d1", tenant_id="t1")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(bp["topics"][0]["topic_name"], "A")

    def test_invalid_plan_cannot_silently_drop_source_topic(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("A")])])
        synth = MasterBlueprintSynthesizer(service=fake)

        dirty = {
            "topic_groups": [
                {"topic_name": "Invented", "source_topic_ids": ["T9999"]},
                "junk",
            ],
            "discarded_source_topic_ids": [],
        }
        with patch(f"{MODULE}.complete_json_large", return_value=(dirty, "gemini")):
            bp = synth.synthesize(document_id="d1", tenant_id="t1")
        self.assertEqual([t["topic_name"] for t in bp["topics"]], ["A"])

    def test_tenant_scoped(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("Mine")])])
        fake.seed("d1", "OTHER", [(0, "succeeded", [_topic("Theirs")])])
        synth = MasterBlueprintSynthesizer(service=fake)

        with patch(
            f"{MODULE}.complete_json_large", return_value=(MERGE_PLAN, "gemini")
        ) as call:
            bp = synth.synthesize(document_id="d1", tenant_id="t1")

        self.assertEqual(bp["source_topic_count"], 1)
        _system, user = call.call_args.args
        self.assertIn("Mine", user)
        self.assertNotIn("Theirs", user)

    def test_verbatim_spot_check_matches_and_warns_without_blocking(self) -> None:
        topics = [
            _topic(
                "Strings",
                key_facts_and_figures=[
                    "Python strings support indexing and slicing operations",
                    "This invented statement is absent from every source section",
                ],
                source_page_ranges=[{"start": 1, "end": 12}],
            )
        ]
        chunks = [{
            "content": "Python strings support indexing and slicing operations.",
            "page_start": 1,
            "page_end": 12,
        }]
        with self.assertLogs(MODULE, level="WARNING") as logs:
            result = spot_check_verbatim_facts(topics, chunks)
        self.assertEqual(result, {"checked": 2, "matched": 1, "warnings": 1})
        self.assertIn("failed verbatim spot-check", "\n".join(logs.output))

    def test_reduce_excerpts_are_rechecked_against_attributed_chunk(self) -> None:
        topics = [_topic(
            "Treaty",
            source_page_ranges=[{"start": 90, "end": 90}],
        )]
        topics[0]["source_excerpts"] = [
            {"text": "The treaty was signed in Versailles on 28 June 1919."},
            {"text": "This invented sentence never appeared in the source."},
        ]
        chunks = [{
            "content": "The treaty was signed in Versailles on 28 June 1919.",
            "page_start": 90,
            "page_end": 90,
        }]
        with self.assertLogs(MODULE, level="WARNING"):
            dropped = keep_verified_source_excerpts(topics, chunks)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(topics[0]["source_excerpts"]), 1)

    def test_reduce_keeps_symbolic_excerpt_with_unicode_normalisation(self) -> None:
        topics = [_topic("Electric power")]
        topics[0]["source_excerpts"] = [{"text": "P = VI = I²R"}]
        chunks = [{"content": "Formula: P = VI = I2R", "page_start": 2, "page_end": 2}]

        dropped = keep_verified_source_excerpts(topics, chunks)

        self.assertEqual(dropped, 0)
        self.assertEqual(topics[0]["source_excerpts"], [{"text": "P = VI = I²R"}])

    def test_reduce_cannot_broaden_source_topic_name(self) -> None:
        source = _topic("Potential Energy", formulas=[{"name": "Potential Energy", "formula": "PE = mgh"}])
        plan = {
            "topic_groups": [{
                "topic_name": "Conservation of Energy",
                "source_topic_ids": ["T0001"],
            }],
            "discarded_source_topic_ids": [],
        }

        merged = apply_merge_plan([source], plan)

        self.assertEqual(merged[0]["topic_name"], "Potential Energy")

    def test_reduce_preserves_distinct_source_names_when_plan_over_groups(self) -> None:
        sources = [
            _topic("Estates-General"),
            _topic("Reign of Terror"),
            _topic("Directory"),
        ]
        plan = {
            "topic_groups": [{
                "topic_name": "French Revolution",
                "source_topic_ids": ["T0001", "T0002", "T0003"],
            }],
            "discarded_source_topic_ids": [],
        }

        merged = apply_merge_plan(sources, plan)

        # The unsupported broad label is rejected, but all three original
        # assessable concepts remain available to the topic-choice layer.
        self.assertEqual(merged[0]["topic_name"], "Estates-General")
        self.assertEqual(
            merged[0]["source_topic_names"],
            ["Estates-General", "Reign of Terror", "Directory"],
        )

    def test_reduce_ai_call_consumes_the_shared_rate_limit(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("A")])])
        profile = CurrentProfile(user_id="u1", tenant_id="t1", role="teacher")
        synth = MasterBlueprintSynthesizer(service=fake)
        with patch(
            f"{MODULE}.get_settings",
            return_value=SimpleNamespace(rate_limit_topic_extraction_per_hour=10),
        ), patch(f"{MODULE}.enforce_ai_rate_limit") as limit, patch(
            f"{MODULE}.complete_json_large", return_value=(MERGE_PLAN, "gemini")
        ):
            synth.synthesize(document_id="d1", tenant_id="t1", profile=profile)
        limit.assert_called_once()
        self.assertEqual(limit.call_args.kwargs["profile"], profile)

    def test_reduce_retry_has_enough_budget_and_logs_original_failure(self) -> None:
        fake = _Fake()
        fake.seed("d1", "t1", [(0, "succeeded", [_topic("A")])])
        profile = CurrentProfile(user_id="u1", tenant_id="t1", role="teacher")
        synth = MasterBlueprintSynthesizer(service=fake)
        with patch(
            f"{MODULE}.get_settings",
            return_value=SimpleNamespace(rate_limit_topic_extraction_per_hour=30),
        ), patch(f"{MODULE}.enforce_ai_rate_limit") as limit, patch(
            f"{MODULE}.complete_json_large",
            side_effect=[LLMError("provider timed out"), (MERGE_PLAN, "gemini")],
        ), self.assertLogs(MODULE, level="WARNING") as logs:
            bp = synth.synthesize(document_id="d1", tenant_id="t1", profile=profile)
        self.assertEqual(limit.call_count, 2)
        self.assertEqual(bp["topics"][0]["topic_name"], "A")
        self.assertIn("provider timed out", "\n".join(logs.output))

    def test_merge_plan_preserves_full_verbatim_material_server_side(self) -> None:
        first = _topic(
            "Compound interest",
            subtopics=["annual compounding"],
            key_facts_and_figures=["The principal is ₹10,000 at 8% per annum."],
            source_page_ranges=[{"start": 280, "end": 282}],
        )
        first["source_excerpts"] = [{
            "text": "The principal is ₹10,000 at 8% per annum for three years.",
            "page_start": 280,
            "page_end": 282,
        }]
        second = _topic(
            "Interest compounded annually",
            subtopics=["annual compounding", "maturity value"],
            key_facts_and_figures=["The maturity value after three years is ₹12,597.12."],
            source_page_ranges=[{"start": 282, "end": 284}],
        )
        plan = {
            "topic_groups": [{
                "topic_name": "Compound interest",
                "source_topic_ids": ["T0001", "T0002"],
            }],
            "discarded_source_topic_ids": [],
        }

        catalogue = build_topic_catalogue([first, second])
        self.assertNotIn("key_facts_and_figures", catalogue[0])
        merged = apply_merge_plan([first, second], plan)

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["key_facts_and_figures"],
            [
                "The principal is ₹10,000 at 8% per annum.",
                "The maturity value after three years is ₹12,597.12.",
            ],
        )
        self.assertEqual(merged[0]["source_excerpts"], first["source_excerpts"])
        self.assertEqual(
            merged[0]["source_page_ranges"],
            [{"start": 280, "end": 282}, {"start": 282, "end": 284}],
        )


if __name__ == "__main__":
    unittest.main()
