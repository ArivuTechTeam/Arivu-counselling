"""Phase 6.3-B/D: commerce context resolution and prompt injection.

Resolution must be best-effort (never raise) and the prompt must be byte-identical
when there is no context, so a non-commerce tenant is entirely unaffected.
"""

from __future__ import annotations

import unittest

from app.services.blueprint_prompts import build_blueprint_system_prompt
from app.services.commerce_context import format_commerce_context, resolve_paper_profile

TYPES = ["mcq_single", "numerical"]

FULL = {
    "exam_body": "ICAI",
    "level": "Foundation",
    "paper": "Paper 4",
    "assessment_year": "2025-26",
    "framework": "Indian GAAP",
}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, result):
        self._result = result

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return self._result


class _Service:
    """Fake Supabase client: maps table name -> the _Resp its query resolves to."""

    def __init__(self, tables, *, raise_on=None):
        self._tables = tables
        self._raise_on = raise_on

    def table(self, name):
        if self._raise_on == name:
            raise RuntimeError("boom")
        return _Query(self._tables.get(name, _Resp(None)))


def _service(subject_course_id, profile, *, raise_on=None):
    return _Service(
        {
            "subjects": _Resp({"course_id": subject_course_id, "course_level_id": "level-1"} if subject_course_id else None),
            "paper_profiles": _Resp(profile),
        },
        raise_on=raise_on,
    )


class ResolveTests(unittest.TestCase):
    def test_resolves_profile_through_subject_and_course(self):
        service = _service("course-1", {**FULL, "course_id": "course-1", "course_level_id": "level-1"})
        self.assertEqual(resolve_paper_profile(service, "t1", "subj-1")["exam_body"], "ICAI")

    def test_no_subject_returns_none(self):
        self.assertIsNone(resolve_paper_profile(_service(None, None), "t1", "subj-x"))

    def test_no_profile_returns_none(self):
        self.assertIsNone(resolve_paper_profile(_service("course-1", None), "t1", "subj-1"))

    def test_all_blank_profile_returns_none(self):
        blank = {k: "  " for k in FULL}
        self.assertIsNone(resolve_paper_profile(_service("course-1", blank), "t1", "subj-1"))

    def test_lookup_error_degrades_to_none(self):
        service = _service("course-1", FULL, raise_on="subjects")
        self.assertIsNone(resolve_paper_profile(service, "t1", "subj-1"))


class FormatTests(unittest.TestCase):
    def test_full_profile(self):
        self.assertEqual(
            format_commerce_context(FULL),
            "exam ICAI Foundation Paper 4; assessment year 2025-26; framework Indian GAAP",
        )

    def test_only_assessment_year(self):
        self.assertEqual(
            format_commerce_context({"assessment_year": "2025-26"}),
            "assessment year 2025-26",
        )

    def test_only_exam_body(self):
        self.assertEqual(format_commerce_context({"exam_body": "ACCA"}), "exam ACCA")

    def test_none_and_blank(self):
        self.assertIsNone(format_commerce_context(None))
        self.assertIsNone(format_commerce_context({k: "" for k in FULL}))


class PromptInjectionTests(unittest.TestCase):
    def test_no_context_is_byte_identical(self):
        default = build_blueprint_system_prompt(TYPES, "mixed", "medium")
        explicit_none = build_blueprint_system_prompt(
            TYPES, "mixed", "medium", commerce_context=None
        )
        self.assertEqual(default, explicit_none)
        self.assertNotIn("COMMERCE CONTEXT", default)

    def test_context_is_appended_and_extends_base(self):
        context = "exam ICAI Foundation Paper 4; assessment year 2025-26"
        base = build_blueprint_system_prompt(TYPES, "mixed", "medium")
        withctx = build_blueprint_system_prompt(
            TYPES, "mixed", "medium", commerce_context=context
        )
        self.assertIn("COMMERCE CONTEXT", withctx)
        self.assertIn(context, withctx)
        # Purely additive: the base instructions are still present verbatim.
        self.assertIn(base.replace("Return the JSON object now — JSON only.", ""), withctx)

    def test_context_and_calc_coexist(self):
        withboth = build_blueprint_system_prompt(
            TYPES, "mixed", "medium",
            commerce_calc_enabled=True, commerce_context="exam ACCA",
        )
        self.assertIn("COMMERCE CONTEXT", withboth)
        self.assertIn("OPTIONAL NUMERIC CHECK", withboth)


if __name__ == "__main__":
    unittest.main()
