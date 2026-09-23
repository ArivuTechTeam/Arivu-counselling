"""Phase 6.3-C: numeric & table extraction fidelity (commerce pack).

All behaviour here is gated behind COMMERCE_PACK_ENABLED and must degrade to the
existing plain extraction whenever table detection is unavailable or errors.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import extraction as ext
from app.services import source_material as sm
from app.services.extraction import ExtractedText, PageSpan, _extract_pdf_page_text


class _Table:
    def __init__(self, bbox, rows):
        self.bbox = bbox
        self._rows = rows

    def extract(self):
        return self._rows


class _Page:
    """A minimal pdfplumber-like page. `find_tables` may be a value or a callable
    that raises, to exercise the fallback contract."""

    def __init__(self, chars, tables="__none__"):
        self.chars = chars
        self._tables = tables

    def find_tables(self):
        if self._tables == "__none__":
            raise RuntimeError("no table finder configured")
        if callable(self._tables):
            return self._tables()
        return self._tables


# Prose char sits outside the table bbox; the two digit chars sit inside it and
# must be pulled OUT of the linear prose (they are recovered via the table rows).
PROSE = {"text": "A", "x0": 0, "x1": 5, "top": 0, "bottom": 5, "size": 11}
INSIDE_1 = {"text": "9", "x0": 148, "x1": 152, "top": 148, "bottom": 152, "size": 11}
INSIDE_2 = {"text": "8", "x0": 158, "x1": 162, "top": 148, "bottom": 152, "size": 11}
BBOX = (100, 100, 200, 200)
ROWS = [["Cash", "1,00,000"], ["Bank", "2,00,000"]]

# extract_pdf_chars is patched to concatenate char text, matching the existing
# page-span tests, so we can assert exactly which chars reach the prose stream.
_CONCAT = lambda mapped, **_k: "".join(str(c["text"]) for c in mapped)


def _settings(enabled):
    return SimpleNamespace(commerce_pack_enabled=enabled)


class PdfTableRecoveryTests(unittest.TestCase):
    def _run(self, page, *, enabled):
        with patch.object(ext, "get_settings", return_value=_settings(enabled)), patch.object(
            ext, "extract_pdf_chars", side_effect=_CONCAT
        ):
            return _extract_pdf_page_text(page)

    def test_flag_off_is_byte_identical(self):
        page = _Page([PROSE, INSIDE_1, INSIDE_2], tables=[_Table(BBOX, ROWS)])
        # With the flag off the table finder is never consulted: plain concat.
        self.assertEqual(self._run(page, enabled=False), "A98")

    def test_table_columns_stay_bound_to_row_labels(self):
        page = _Page([PROSE, INSIDE_1, INSIDE_2], tables=[_Table(BBOX, ROWS)])
        result = self._run(page, enabled=True)
        self.assertIn("Cash | 1,00,000", result)
        self.assertIn("Bank | 2,00,000", result)
        self.assertIn("=== TABLE ===", result)
        # Prose keeps the outside char; the in-table digits are not left dangling
        # in the linear prose (they are only present inside the structured rows).
        self.assertTrue(result.startswith("A"))
        self.assertNotIn("A98", result)

    def test_no_tables_detected_falls_back(self):
        page = _Page([PROSE, INSIDE_1, INSIDE_2], tables=[])
        self.assertEqual(self._run(page, enabled=True), "A98")

    def test_finder_error_falls_back(self):
        def boom():
            raise ValueError("pdfplumber blew up")

        page = _Page([PROSE, INSIDE_1, INSIDE_2], tables=boom)
        self.assertEqual(self._run(page, enabled=True), "A98")

    def test_missing_find_tables_falls_back(self):
        page = type("P", (), {"chars": [PROSE, INSIDE_1, INSIDE_2]})()
        self.assertEqual(self._run(page, enabled=True), "A98")

    def test_empty_table_rows_fall_back_to_plain_text(self):
        page = _Page([PROSE, INSIDE_1, INSIDE_2], tables=[_Table(BBOX, [[None, None]])])
        # Nothing usable rendered -> plain extraction, digits retained.
        self.assertEqual(self._run(page, enabled=True), "A98")


class SafeTruncationTests(unittest.TestCase):
    TEXT = "abc 1,00,000 def"  # the number spans indices 4..11

    def _end(self, text, start, end, *, enabled):
        with patch.object(sm, "get_settings", return_value=_settings(enabled)):
            return sm._safe_truncation_end(text, start, end)

    def test_flag_off_never_moves_the_cut(self):
        self.assertEqual(self._end(self.TEXT, 0, 8, enabled=False), 8)

    def test_no_truncation_when_end_is_document_end(self):
        self.assertEqual(self._end(self.TEXT, 0, len(self.TEXT), enabled=True), len(self.TEXT))

    def test_cut_on_whitespace_is_unchanged(self):
        # index 3 is the space after "abc"; text[3] is space -> no split.
        self.assertEqual(self._end(self.TEXT, 0, 3, enabled=True), 3)

    def test_mid_number_cut_is_pulled_back_to_whitespace(self):
        # Cutting at 8 lands inside "1,00,000"; back off to end of "abc" (3), the
        # last complete token, dropping the boundary whitespace too.
        self.assertEqual(self._end(self.TEXT, 0, 8, enabled=True), 3)

    def test_no_whitespace_in_range_keeps_end(self):
        number = "1,00,000"
        self.assertEqual(self._end(number, 0, 4, enabled=True), 4)


class SafeTruncationRenderTests(unittest.TestCase):
    def test_docx_material_not_cut_mid_number_when_enabled(self):
        extracted = ExtractedText(text="Revenue 1,00,000 crore reported", page_spans=())
        with patch.object(sm, "get_settings", return_value=_settings(True)):
            out = sm.render_extracted_material(extracted, max_chars=12)
        # max_chars=12 lands inside the number; output must end on a clean token.
        self.assertEqual(out, "Revenue")
        self.assertNotIn("1,00", out)

    def test_render_byte_identical_when_no_truncation(self):
        extracted = ExtractedText(text="short text", page_spans=())
        with patch.object(sm, "get_settings", return_value=_settings(True)):
            out = sm.render_extracted_material(extracted, max_chars=100)
        self.assertEqual(out, "short text")


if __name__ == "__main__":
    unittest.main()
