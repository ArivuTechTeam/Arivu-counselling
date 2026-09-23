from __future__ import annotations

import unittest

from app.services.figure_matching import (
    match_question_figure,
    references_a_figure,
)

_CATALOG = [
    {"id": "f81", "page": 8, "label": "Figure 8.1"},
    {"id": "f82", "page": 8, "label": "Figure 8.2"},
    {"id": "f34", "page": 3, "label": "Fig. 3.4"},
    {"id": "d2", "page": 5, "label": "Diagram 2"},
]


class ReferencesAFigureTests(unittest.TestCase):
    def test_detects_figure_dependent_stems(self) -> None:
        for text in [
            "In the given figure, find the value of angle x.",
            "The diagram shows a triangle ABC.",
            "Study the following figure and answer.",
            "As illustrated below, calculate the area.",
        ]:
            self.assertTrue(references_a_figure(text), text)

    def test_ignores_self_contained_stems(self) -> None:
        for text in [
            "Compute 12 x 4.",
            "Define photosynthesis.",
            "A triangle has sides 3, 4 and 5. Find its area.",
        ]:
            self.assertFalse(references_a_figure(text), text)


class MatchQuestionFigureTests(unittest.TestCase):
    def test_explicit_label_wins_regardless_of_page(self) -> None:
        # Names Figure 8.1 explicitly; page hint points elsewhere — label wins.
        fid = match_question_figure(
            _CATALOG,
            question_text="Using Figure 8.1, determine the marked angle.",
            page_start=3,
            page_end=3,
        )
        self.assertEqual(fid, "f81")

    def test_label_form_tolerance(self) -> None:
        # "Fig 3.4" in the stem should match the catalog's "Fig. 3.4".
        fid = match_question_figure(
            _CATALOG, question_text="Refer to Fig 3.4 and find x.", page_start=99
        )
        self.assertEqual(fid, "f34")

    def test_mention_plus_single_page_match(self) -> None:
        # Generic mention, exactly one figure on page 3 -> attach it.
        fid = match_question_figure(
            _CATALOG,
            question_text="In the given figure, find the angle.",
            page_start=3,
            page_end=3,
        )
        self.assertEqual(fid, "f34")

    def test_ambiguous_page_returns_none(self) -> None:
        # Two figures on page 8 and no explicit label -> do not guess.
        self.assertIsNone(
            match_question_figure(
                _CATALOG,
                question_text="In the figure, name the labelled part.",
                page_start=8,
                page_end=8,
            )
        )

    def test_no_reference_returns_none(self) -> None:
        self.assertIsNone(
            match_question_figure(
                _CATALOG, question_text="Compute the mean of 2, 4, 6.", page_start=8
            )
        )

    def test_empty_catalog_returns_none(self) -> None:
        self.assertIsNone(
            match_question_figure(
                [], question_text="In Figure 8.1, find x.", page_start=8
            )
        )

    def test_mention_but_no_figure_on_page(self) -> None:
        self.assertIsNone(
            match_question_figure(
                _CATALOG,
                question_text="In the given figure, find the angle.",
                page_start=99,
            )
        )


if __name__ == "__main__":
    unittest.main()
