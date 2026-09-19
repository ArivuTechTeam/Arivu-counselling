from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.quiz_generator_service import (
    QuizGeneratorService,
    render_blueprint_material,
    render_blueprint_material_with_evidence,
)

GEN_MODULE = "app.services.quiz_generator_service"
BP_MODULE = "app.services.blueprint"

BLUEPRINT = {
    "document_title": "Strings",
    "topics": [
        {
            "topic_name": "What Is a String?",
            "subtopics": ["literals", "length"],
            "key_definitions": [{"term": "character", "definition": "a single symbol"}],
            "key_facts_and_figures": ["strings are immutable"],
            "formulas": [],
            "worked_examples": [{"description": "index", "full_example_text": "s[0] == 'H'"}],
            "source_excerpts": [{
                "text": "A string is an immutable sequence of characters.",
                "page_start": 4,
                "page_end": 4,
            }],
        }
    ],
}


class RenderTests(unittest.TestCase):
    def test_renders_verbatim_content(self) -> None:
        text = render_blueprint_material(BLUEPRINT)
        self.assertIn("## What Is a String?", text)
        self.assertIn("Subtopics: literals, length", text)
        self.assertIn("Definition — character: a single symbol", text)
        self.assertIn("Fact: strings are immutable", text)
        self.assertIn("Worked example: s[0] == 'H'", text)

    def test_skips_empty_topics(self) -> None:
        self.assertEqual(render_blueprint_material({"topics": [{"topic_name": ""}]}), "")
        self.assertEqual(render_blueprint_material({}), "")

    def test_selecting_child_renders_its_parent_evidence(self) -> None:
        blueprint = {"topics": [{
            "topic_name": "Electromagnetism",
            "subtopics": ["Ohm's Law", "Coulomb's Law"],
            "formulas": [{"name": "Ohm's Law", "formula": "V = IR"}],
            "source_excerpts": [{"text": "Ohm's law is written as V = IR."}],
        }]}
        text = render_blueprint_material(blueprint, {"ohm's law"})
        self.assertIn("## Electromagnetism", text)
        self.assertIn("V = IR", text)

    def test_assigns_stable_ids_to_verified_source_excerpts(self) -> None:
        material, catalog = render_blueprint_material_with_evidence(BLUEPRINT)
        self.assertIn('Source excerpt [E0001]', material)
        self.assertEqual(
            catalog["E0001"]["text"],
            "A string is an immutable sequence of characters.",
        )
        self.assertEqual(catalog["E0001"]["page_start"], 4)


# --- fake supabase supporting the job load + link update --------------------

class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op, self.filters, self.payload, self._single = "select", [], None, False

    def select(self, *_a):
        self.op = "select"; return self

    def update(self, values):
        self.op, self.payload = "update", values; return self

    def eq(self, k, v):
        self.filters.append((k, v)); return self

    def maybe_single(self):
        self._single = True; return self

    def _match(self, r):
        return all(r.get(k) == v for k, v in self.filters)

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "select":
            out = [dict(r) for r in rows if self._match(r)]
            return type("R", (), {"data": (out[0] if out else None) if self._single else out})
        if self.op == "update":
            changed = []
            for r in rows:
                if self._match(r):
                    r.update(self.payload); changed.append(dict(r))
            return type("R", (), {"data": changed})
        return type("R", (), {"data": []})


class _Fake:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Query(self.db, name)


def _profile():
    return SimpleNamespace(user_id="u1", tenant_id="t1", role="teacher")


def _seed_job(fake, *, status="completed", blueprint=BLUEPRINT):
    fake.db["quiz_generation_jobs"] = [
        {
            "id": "j1", "tenant_id": "t1", "created_by": "u1",
            "document_id": "d1", "status": status, "master_blueprint": blueprint,
        }
    ]


class GenerateFromJobTests(unittest.TestCase):
    def _call(self, fake):
        svc = QuizGeneratorService(service=fake)
        return svc.generate_from_job(
            job_id="j1", subject_id="s1", chapter_name="Strings",
            selected_topics=[{"name": "What Is a String?", "weight": "high"}],
            total_questions=3, question_types=["mcq_single"],
            cognitive_level="mixed", difficulty="medium", profile=_profile(),
        )

    def test_generates_and_links_quiz_set_to_job(self) -> None:
        fake = _Fake(); _seed_job(fake)
        with patch(f"{GEN_MODULE}.get_settings", return_value=SimpleNamespace(
            generation_max_text_chars=1_000_000
        )), patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material",
            return_value={"quiz_set_id": "qs1", "questions": []},
        ) as gen:
            result = self._call(fake)

        self.assertEqual(result["quiz_set_id"], "qs1")
        self.assertEqual(result["job_id"], "j1")
        # material rendered from the blueprint was passed to the writer
        material = gen.call_args.kwargs["material"]
        self.assertIn("What Is a String?", material)
        self.assertEqual(gen.call_args.kwargs["source_document_id"], "d1")
        self.assertEqual(
            gen.call_args.kwargs["evidence_catalog"]["E0001"]["page_start"], 4
        )
        # quiz_set linked back onto the job
        self.assertEqual(fake.db["quiz_generation_jobs"][0]["quiz_set_id"], "qs1")
        self.assertEqual(
            fake.db["quiz_generation_jobs"][0]["params"]["selected_topics"],
            [{"name": "What Is a String?", "weight": "high"}],
        )

    def test_rejects_job_not_ready(self) -> None:
        fake = _Fake(); _seed_job(fake, status="running", blueprint=None)
        with patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material"
        ) as gen:
            with self.assertRaisesRegex(ValueError, "isn't ready"):
                self._call(fake)
        gen.assert_not_called()

    def test_partial_job_is_blocked(self) -> None:
        fake = _Fake(); _seed_job(fake, status="partial")
        with patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material",
            return_value={"quiz_set_id": "qs1"},
        ) as gen:
            with self.assertRaisesRegex(ValueError, "isn't ready"):
                self._call(fake)
        gen.assert_not_called()

    def test_sends_only_selected_topic_material_without_truncation(self) -> None:
        early = {**BLUEPRINT["topics"][0], "topic_name": "Early", "key_facts_and_figures": ["EARLY FACT"]}
        late = {**BLUEPRINT["topics"][0], "topic_name": "Late", "key_facts_and_figures": ["LATE PAGE 95 FACT"]}
        fake = _Fake(); _seed_job(fake, blueprint={"topics": [early, late]})
        svc = QuizGeneratorService(service=fake)
        with patch(f"{GEN_MODULE}.get_settings", return_value=SimpleNamespace(
            generation_max_text_chars=1_000_000
        )), patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material",
            return_value={"quiz_set_id": "qs1", "questions": []},
        ) as gen:
            result = svc.generate_from_job(
                job_id="j1", subject_id="s1", chapter_name="Late",
                selected_topics=[{"name": "Late", "weight": "high"}],
                total_questions=1, question_types=["mcq_single"],
                cognitive_level="mixed", difficulty="medium", profile=_profile(),
            )
        material = gen.call_args.kwargs["material"]
        self.assertIn("LATE PAGE 95 FACT", material)
        self.assertNotIn("EARLY FACT", material)
        self.assertTrue(gen.call_args.kwargs["selected_only_material"])
        self.assertEqual(result["source_material_chars"], len(material))

    def test_oversized_selected_material_fails_instead_of_slicing(self) -> None:
        huge = {**BLUEPRINT["topics"][0], "key_facts_and_figures": ["x" * 500]}
        fake = _Fake(); _seed_job(fake, blueprint={"topics": [huge]})
        with patch(f"{GEN_MODULE}.get_settings", return_value=SimpleNamespace(
            generation_max_text_chars=100
        )), patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material"
        ) as gen:
            with self.assertRaisesRegex(ValueError, "too much source material"):
                self._call(fake)
        gen.assert_not_called()

    def test_missing_job_raises(self) -> None:
        fake = _Fake()  # no job seeded
        with patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True):
            with self.assertRaisesRegex(ValueError, "not found"):
                self._call(fake)

    def test_subject_check_enforced(self) -> None:
        fake = _Fake(); _seed_job(fake)
        with patch(f"{GEN_MODULE}.teacher_has_subject", return_value=False), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material"
        ) as gen:
            with self.assertRaisesRegex(ValueError, "Subject not found"):
                self._call(fake)
        gen.assert_not_called()

    def test_accepts_promoted_child_as_selected_topic(self) -> None:
        blueprint = {"topics": [{
            "topic_name": "Electromagnetism",
            "subtopics": ["Ohm's Law", "Coulomb's Law"],
            "formulas": [
                {"name": "Ohm's Law", "formula": "V = IR"},
                {"name": "Coulomb's Law", "formula": "F = k(q1q2)/r²"},
            ],
            "source_excerpts": [{"text": "Ohm's law is written as V = IR."}],
        }]}
        fake = _Fake(); _seed_job(fake, blueprint=blueprint)
        svc = QuizGeneratorService(service=fake)
        with patch(f"{GEN_MODULE}.get_settings", return_value=SimpleNamespace(
            generation_max_text_chars=1_000_000
        )), patch(f"{GEN_MODULE}.teacher_has_subject", return_value=True), patch(
            f"{GEN_MODULE}.generate_and_persist_from_material",
            return_value={"quiz_set_id": "qs1", "questions": []},
        ) as gen:
            svc.generate_from_job(
                job_id="j1", subject_id="s1", chapter_name="Physics",
                selected_topics=[{"name": "Ohm's Law", "weight": "high"}],
                total_questions=2, question_types=["mcq_single"],
                cognitive_level="mixed", difficulty="medium", profile=_profile(),
            )
        self.assertIn("V = IR", gen.call_args.kwargs["material"])


if __name__ == "__main__":
    unittest.main()
