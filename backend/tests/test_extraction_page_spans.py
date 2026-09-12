from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.extraction import extract_text_with_pages


class _Page:
    def __init__(self, text: str | None) -> None:
        self._text = text

    def extract_text(self) -> str | None:
        return self._text


class _Pdf:
    def __init__(self, pages: list[_Page]) -> None:
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class ExtractionPageSpanTests(unittest.TestCase):
    def test_pdf_offsets_survive_outer_whitespace_trimming(self) -> None:
        fake_pdf = _Pdf([_Page("  page one"), _Page("page two  ")])
        with patch("app.services.extraction.pdfplumber.open", return_value=fake_pdf):
            result = extract_text_with_pages(b"pdf", "pdf")

        self.assertEqual(result.text, "page one\n\npage two")
        self.assertEqual(
            [(span.page_number, span.char_start, span.char_end) for span in result.page_spans],
            [(1, 0, 8), (2, 10, 18)],
        )

    def test_docx_keeps_existing_text_contract_without_fake_pages(self) -> None:
        with patch("app.services.extraction._extract_docx", return_value="body"):
            result = extract_text_with_pages(b"docx", "docx")
        self.assertEqual(result.text, "body")
        self.assertEqual(result.page_spans, ())


if __name__ == "__main__":
    unittest.main()
