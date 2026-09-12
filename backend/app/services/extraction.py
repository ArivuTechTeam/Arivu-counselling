"""
Text extraction from uploaded documents.

Slice 2 supports the two text-based formats from the scoping doc:
  - PDF  -> pdfplumber
  - DOCX -> python-docx

Scanned/image-only PDFs (which need OCR or vision extraction) are intentionally
out of scope for the text-based upload flow. Callers can use
``MIN_READABLE_PDF_TEXT_CHARS`` to reject PDFs without a usable text layer.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


# Keep this aligned with the existing authored-quiz extraction branch. A few
# stray PDF metadata glyphs must not make an image-only scan look readable.
MIN_READABLE_PDF_TEXT_CHARS = 200


@dataclass(frozen=True)
class PageSpan:
    """Approximate page provenance inside the extracted plain-text string."""

    page_number: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ExtractedText:
    text: str
    page_spans: tuple[PageSpan, ...] = ()


def extract_text(content: bytes, ext: str) -> str:
    """Extract plain text from a document's bytes, chosen by file extension."""
    return extract_text_with_pages(content, ext).text


def extract_text_with_pages(content: bytes, ext: str) -> ExtractedText:
    """Extract text plus approximate PDF page offsets.

    DOCX has no stable page concept without rendering, so it intentionally returns
    an empty page map while preserving the existing plain-text behaviour.
    """
    ext = ext.lower()
    if ext == "pdf":
        return _extract_pdf_with_pages(content)
    if ext == "docx":
        return ExtractedText(_extract_docx(content))
    raise ValueError(f"Unsupported file type: .{ext}")


def _extract_pdf(content: bytes) -> str:
    return _extract_pdf_with_pages(content).text


def _extract_pdf_with_pages(content: bytes) -> ExtractedText:
    # io.BytesIO wraps the in-memory bytes so pdfplumber can read them like a file.
    parts: list[str] = []
    untrimmed_spans: list[PageSpan] = []
    cursor = 0
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            if parts:
                cursor += 2  # the page separator inserted by join below
            page_text = page.extract_text() or ""
            start = cursor
            cursor += len(page_text)
            untrimmed_spans.append(PageSpan(page_number, start, cursor))
            parts.append(page_text)

    untrimmed = "\n\n".join(parts)
    leading = len(untrimmed) - len(untrimmed.lstrip())
    text = untrimmed.strip()
    text_length = len(text)
    spans = tuple(
        PageSpan(
            span.page_number,
            min(text_length, max(0, span.char_start - leading)),
            min(text_length, max(0, span.char_end - leading)),
        )
        for span in untrimmed_spans
    )
    return ExtractedText(text=text, page_spans=spans)


def _extract_docx(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    parts: list[str] = []

    # ``doc.paragraphs`` omits tables. Walk the document body so prose and table
    # rows stay in their original order and table-only teaching material is not
    # silently lost before topic extraction.
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, doc).text.strip()
            if text:
                parts.append(text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))

    return "\n".join(parts).strip()
