from __future__ import annotations

import unittest

import pymupdf

from app.services.figure_extraction import (
    _CAPTION_RE,
    _dedupe_caption,
    extract_document_figures,
)


def _pdf_with_figure(caption: str = "Figure 1.2 A sample diagram") -> bytes:
    """A one-page PDF: a drawn shape (the figure) with a caption below it."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.draw_rect(
        pymupdf.Rect(100, 100, 300, 250), color=(0, 0, 0), fill=(0.8, 0.8, 0.8)
    )
    page.insert_text((100, 275), caption, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _pdf_text_only() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((72, 100), "Just body text, no figures here.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class CaptionRegexTests(unittest.TestCase):
    def test_matches_real_captions(self) -> None:
        for good in ["Figure 8.1 Diagram of a cell", "Fig 3.4 (i) to (iv)", "Diagram 2"]:
            self.assertTrue(_CAPTION_RE.match(good), good)

    def test_ignores_in_body_mentions(self) -> None:
        for bad in ["as shown in Figure 3.1", "The figure below", "see fig. later"]:
            self.assertIsNone(_CAPTION_RE.match(bad), bad)


class DedupeCaptionTests(unittest.TestCase):
    def test_collapses_repeated_leading_label(self) -> None:
        self.assertEqual(
            _dedupe_caption("Figure 5.2 Figure 5.2 Figure 5.2"), "Figure 5.2"
        )

    def test_collapses_repeat_then_keeps_unique_tail(self) -> None:
        self.assertEqual(
            _dedupe_caption("Figure 5.2 Figure 5.2 Diagram of a nephron"),
            "Figure 5.2 Diagram of a nephron",
        )

    def test_leaves_clean_captions_untouched(self) -> None:
        for good in ["Figure 5.4 Experimental set-up (a)", "Fig 3.4 (i) to (iv)"]:
            self.assertEqual(_dedupe_caption(good), good)


class ExtractDocumentFiguresTests(unittest.TestCase):
    def test_extracts_a_captioned_figure_with_label_and_png(self) -> None:
        figures = extract_document_figures(_pdf_with_figure())
        self.assertEqual(len(figures), 1)
        fig = figures[0]
        self.assertEqual(fig.page, 1)
        self.assertEqual(fig.label, "Figure 1.2")
        self.assertIn("sample diagram", fig.caption)
        self.assertTrue(fig.png_bytes.startswith(b"\x89PNG"))  # real PNG
        self.assertGreater(fig.width, 0)
        self.assertGreater(fig.height, 0)

    def test_no_figure_when_no_caption(self) -> None:
        self.assertEqual(extract_document_figures(_pdf_text_only()), [])

    def test_respects_max_figures_cap(self) -> None:
        # Two captioned figures on separate pages; cap to 1.
        doc = pymupdf.open()
        for label in ("Figure 1.1 first", "Figure 1.2 second"):
            page = doc.new_page(width=400, height=400)
            page.draw_rect(pymupdf.Rect(100, 100, 300, 250), fill=(0.7, 0.7, 0.7))
            page.insert_text((100, 275), label, fontsize=11)
        data = doc.tobytes()
        doc.close()
        self.assertEqual(len(extract_document_figures(data, max_figures=1)), 1)

    def test_bad_bytes_do_not_raise(self) -> None:
        # Extraction is best-effort at the document level via the store wrapper;
        # here a clearly-invalid stream should raise inside pymupdf.open, which the
        # store layer catches. Confirm the function itself surfaces it (caught upstream).
        with self.assertRaises(Exception):
            extract_document_figures(b"not a pdf")


if __name__ == "__main__":
    unittest.main()
