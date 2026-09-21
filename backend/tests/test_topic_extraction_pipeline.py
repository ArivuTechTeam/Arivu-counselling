from __future__ import annotations

import unittest
from unittest.mock import patch

from app.lib.auth import CurrentProfile
from app.services.llm.base import LLMError
from app.services.map_reduce_prompts import MAP_SYSTEM, build_map_user_prompt
from app.services.topic_extraction_pipeline import (
    TopicExtractionPipeline,
    validate_map_output,
)

MODULE = "app.services.topic_extraction_pipeline"

# A realistic rich MAP result the (mocked) model would return for a chunk.
SAMPLE_TOPICS = {
    "topics": [
        {
            "topic_name": "Variables and Types",
            "subtopics": ["integers", "strings"],
            "key_definitions": [{"term": "variable", "definition": "a named store"}],
            "key_facts_and_figures": ["Python is dynamically typed"],
            "formulas": [],
            "worked_examples": [
                {"description": "assignment", "full_example_text": "x = 5"}
            ],
        }
    ]
}


# --- tiny in-memory fake supabase (select/eq/in_/order/update) --------------

class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = "select"
        self.filters = []       # (key, value) equality
        self.in_filters = []    # (key, [values])
        self.payload = None

    def select(self, *_a):
        self.op = "select"
        return self

    def update(self, values):
        self.op = "update"
        self.payload = values
        return self

    def eq(self, k, v):
        self.filters.append((k, v))
        return self

    def in_(self, k, vals):
        self.in_filters.append((k, list(vals)))
        return self

    def order(self, *_a, **_k):
        return self

    def _match(self, row):
        if not all(row.get(k) == v for k, v in self.filters):
            return False
        return all(row.get(k) in vals for k, vals in self.in_filters)

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "select":
            return type("R", (), {"data": [dict(r) for r in rows if self._match(r)]})
        if self.op == "update":
            changed = []
            for r in rows:
                if self._match(r):
                    r.update(self.payload)
                    changed.append(dict(r))
            return type("R", (), {"data": changed})
        return type("R", (), {"data": []})


class _Fake:
    def __init__(self):
        self.db: dict = {}

    def table(self, name):
        return _Query(self.db, name)

    def seed_chunks(self, document_id, tenant_id, count, *, status="queued"):
        rows = self.db.setdefault("document_chunks", [])
        for i in range(count):
            rows.append(
                {
                    "id": f"{tenant_id}-c{i}",
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "chunk_index": i,
                    "content": f"section {i} text",
                    "content_hash": f"h{i}",
                    "map_status": status,
                    "attempts": 0,
                    "topics_json": None,
                    "error_message": None,
                }
            )


class _Settings:  # stand-in so tests run single-threaded + deterministic
    generation_chunk_concurrency = 1
    rate_limit_topic_extraction_per_hour = 10


def _patch_settings():
    return patch(f"{MODULE}.get_settings", return_value=_Settings())


class ValidateOutputTests(unittest.TestCase):
    def test_keeps_wellformed_and_coerces_missing(self) -> None:
        cleaned = validate_map_output({"topics": [{"topic_name": "A"}]})
        self.assertEqual(len(cleaned), 1)
        t = cleaned[0]
        # missing arrays coerced to []
        for key in (
            "subtopics",
            "key_definitions",
            "key_facts_and_figures",
            "formulas",
            "worked_examples",
            "source_page_ranges",
        ):
            self.assertEqual(t[key], [])

    def test_drops_nameless_and_junk(self) -> None:
        data = {"topics": [{"topic_name": ""}, "not-a-dict", {"subtopics": []}]}
        self.assertEqual(validate_map_output(data), [])

    def test_drops_malformed_nested_items(self) -> None:
        data = {
            "topics": [
                {
                    "topic_name": "T",
                    "subtopics": ["ok", "", 5],
                    "key_definitions": [{"term": "x", "definition": "y"}, {"nope": 1}],
                    "formulas": [{"formula": "a=b"}, {"name": "no formula"}],
                    "worked_examples": [{"description": "d"}, {}],
                }
            ]
        }
        t = validate_map_output(data)[0]
        self.assertEqual(t["subtopics"], ["ok"])
        self.assertEqual(len(t["key_definitions"]), 1)
        self.assertEqual(len(t["formulas"]), 1)
        self.assertEqual(len(t["worked_examples"]), 1)

    def test_non_dict_input(self) -> None:
        self.assertEqual(validate_map_output(None), [])
        self.assertEqual(validate_map_output([]), [])

    def test_normalises_source_excerpt_and_page_provenance(self) -> None:
        topic = validate_map_output({"topics": [{
            "topic_name": "Treaty",
            "source_excerpts": [{
                "text": "The treaty was signed in Versailles on 28 June 1919.",
                "page_start": "90",
                "page_end": "91",
            }],
        }]})[0]
        self.assertEqual(topic["source_excerpts"][0]["page_start"], 90)
        self.assertEqual(topic["source_excerpts"][0]["page_end"], 91)


class PromptTests(unittest.TestCase):
    def test_system_prompt_states_contract(self) -> None:
        for token in ("topics", "key_definitions", "formulas", "worked_examples", "VERBATIM"):
            self.assertIn(token, MAP_SYSTEM)
        # It must tell the model to IGNORE non-teachable metadata...
        for token in ("IGNORE", "ISBN", "table of contents"):
            self.assertIn(token, MAP_SYSTEM)
        # ...and to return no topics for a non-teachable section.
        self.assertIn('{"topics": []}', MAP_SYSTEM)
        self.assertIn("faculty-facing units", MAP_SYSTEM)
        self.assertIn("Do not create a separate top-level topic", MAP_SYSTEM)

    def test_user_prompt_injects_context(self) -> None:
        p = build_map_user_prompt(
            document_title="Python Basics", chunk_number=2, total_chunks=3, content="BODY"
        )
        self.assertIn("Python Basics", p)
        self.assertIn("Section 2 of 3", p)
        self.assertIn("BODY", p)

    def test_user_prompt_includes_document_summary(self) -> None:
        p = build_map_user_prompt(
            document_title="Doc",
            chunk_number=1,
            total_chunks=2,
            content="BODY",
            document_summary="Teaches Python strings.",
        )
        self.assertIn("Teaches Python strings.", p)


class RunTests(unittest.TestCase):
    def test_map_keeps_compact_formula_evidence_and_drops_invented_formula(self) -> None:
        pipe = TopicExtractionPipeline(service=_Fake())
        data = {"topics": [{
            "topic_name": "Ohm's Law",
            "formulas": [
                {"name": "Ohm's Law", "formula": "V = IR"},
                {"name": "Invented", "formula": "V = I / R"},
            ],
            "source_excerpts": [{"text": "V = IR"}],
        }]}
        with patch(f"{MODULE}.complete_json_large", return_value=(data, "gemini")):
            topics = pipe._extract(
                document_title="Physics",
                chunk_number=0,
                total_chunks=1,
                content="Equation Focus: Ohm's Law\nV = IR",
                page_start=2,
                page_end=2,
            )

        self.assertEqual(topics[0]["source_excerpts"][0]["text"], "V = IR")
        self.assertEqual(
            [formula["formula"] for formula in topics[0]["formulas"]], ["V = IR"]
        )

    def test_map_replaces_broader_invented_topic_with_explicit_source_term(self) -> None:
        pipe = TopicExtractionPipeline(service=_Fake())
        data = {"topics": [{
            "topic_name": "Conservation of Energy",
            "formulas": [{"name": "Potential Energy", "formula": "PE = mgh"}],
            "source_excerpts": [{"text": "PE = mgh"}],
        }]}
        with patch(f"{MODULE}.complete_json_large", return_value=(data, "gemini")):
            topics = pipe._extract(
                document_title="Physics",
                chunk_number=0,
                total_chunks=1,
                content="Equation Focus: Potential Energy\nPE = mgh",
            )

        self.assertEqual(topics[0]["topic_name"], "Potential Energy")

    def test_map_keeps_only_excerpts_found_verbatim_in_chunk(self) -> None:
        pipe = TopicExtractionPipeline(service=_Fake())
        data = {"topics": [{
            "topic_name": "Treaty",
            "source_excerpts": [
                {"text": "The treaty was signed in Versailles on 28 June 1919."},
                {"text": "This passage was invented and is not in the source."},
            ],
        }]}
        source = "The treaty was signed in Versailles on 28 June 1919."
        with patch(f"{MODULE}.complete_json_large", return_value=(data, "gemini")):
            topics = pipe._extract(
                document_title="History",
                chunk_number=0,
                total_chunks=1,
                content=source,
                page_start=90,
                page_end=90,
            )
        self.assertEqual(len(topics[0]["source_excerpts"]), 1)
        self.assertEqual(topics[0]["source_excerpts"][0]["page_start"], 90)

    def test_all_chunks_mapped_and_checkpointed(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 3)
        pipe = TopicExtractionPipeline(service=fake)

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large",
            return_value=(SAMPLE_TOPICS, "gemini"),
        ) as call:
            result = pipe.run(document_id="d1", tenant_id="t1", document_title="Doc")

        self.assertEqual(result, {"total": 3, "succeeded": 3, "failed": 0})
        self.assertEqual(call.call_count, 3)  # one AI call per chunk
        for row in fake.db["document_chunks"]:
            self.assertEqual(row["map_status"], "succeeded")
            expected = {
                "topics": [{
                    **SAMPLE_TOPICS["topics"][0],
                    "source_excerpts": [],
                    "source_page_ranges": [],
                }]
            }
            self.assertEqual(row["topics_json"], expected)
            self.assertEqual(row["attempts"], 1)
            self.assertIsNone(row["error_message"])

    def test_one_bad_chunk_does_not_sink_others(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 3)
        pipe = TopicExtractionPipeline(service=fake)

        def flaky(_system, user, **_kwargs):
            if "section 1 text" in user:  # chunk index 1 always fails
                raise LLMError("boom")
            return (SAMPLE_TOPICS, "gemini")

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large", side_effect=flaky
        ):
            result = pipe.run(document_id="d1", tenant_id="t1", document_title="Doc")

        self.assertEqual(result, {"total": 3, "succeeded": 2, "failed": 1})
        rows = {r["chunk_index"]: r for r in fake.db["document_chunks"]}
        self.assertEqual(rows[1]["map_status"], "failed")
        self.assertIn("boom", rows[1]["error_message"])
        self.assertEqual(rows[1]["attempts"], 1)  # claimed once (then retried in-call)
        self.assertEqual(rows[0]["map_status"], "succeeded")
        self.assertEqual(rows[2]["map_status"], "succeeded")

    def test_retries_once_then_succeeds(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 1)
        pipe = TopicExtractionPipeline(service=fake)

        calls = {"n": 0}

        def once_flaky(_system, _user, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMError("transient")
            return (SAMPLE_TOPICS, "gemini")

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large", side_effect=once_flaky
        ):
            result = pipe.run(document_id="d1", tenant_id="t1")

        self.assertEqual(result, {"total": 1, "succeeded": 1, "failed": 0})
        self.assertEqual(calls["n"], 2)  # failed once, retried, succeeded

    def test_resume_skips_succeeded_chunks(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 3)
        # chunk 0 already done from a previous run
        fake.db["document_chunks"][0]["map_status"] = "succeeded"
        fake.db["document_chunks"][0]["topics_json"] = SAMPLE_TOPICS
        pipe = TopicExtractionPipeline(service=fake)

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large",
            return_value=(SAMPLE_TOPICS, "gemini"),
        ) as call:
            result = pipe.run(document_id="d1", tenant_id="t1")

        self.assertEqual(result, {"total": 3, "succeeded": 3, "failed": 0})
        self.assertEqual(call.call_count, 2)  # only the 2 pending chunks re-mapped

    def test_nothing_pending_makes_no_calls(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 2, status="succeeded")
        pipe = TopicExtractionPipeline(service=fake)

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large"
        ) as call:
            result = pipe.run(document_id="d1", tenant_id="t1")

        self.assertEqual(result, {"total": 2, "succeeded": 2, "failed": 0})
        call.assert_not_called()

    def test_tenant_scoped(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 2)
        fake.seed_chunks("d1", "OTHER", 2)  # same doc id, different tenant
        pipe = TopicExtractionPipeline(service=fake)

        with _patch_settings(), patch(
            f"{MODULE}.complete_json_large",
            return_value=(SAMPLE_TOPICS, "gemini"),
        ) as call:
            result = pipe.run(document_id="d1", tenant_id="t1", document_title="Doc")

        self.assertEqual(result, {"total": 2, "succeeded": 2, "failed": 0})
        self.assertEqual(call.call_count, 2)
        # the other tenant's rows are untouched
        other = [r for r in fake.db["document_chunks"] if r["tenant_id"] == "OTHER"]
        self.assertTrue(all(r["map_status"] == "queued" for r in other))

    def test_each_map_ai_call_consumes_the_shared_rate_limit(self) -> None:
        fake = _Fake()
        fake.seed_chunks("d1", "t1", 2)
        pipe = TopicExtractionPipeline(service=fake)
        profile = CurrentProfile(user_id="u1", tenant_id="t1", role="teacher")

        with _patch_settings(), patch(
            f"{MODULE}.enforce_ai_rate_limit"
        ) as limit, patch(
            f"{MODULE}.complete_json_large", return_value=(SAMPLE_TOPICS, "gemini")
        ):
            result = pipe.run(document_id="d1", tenant_id="t1", profile=profile)

        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(limit.call_count, 2)
        self.assertTrue(all(c.kwargs["profile"] == profile for c in limit.call_args_list))


if __name__ == "__main__":
    unittest.main()
