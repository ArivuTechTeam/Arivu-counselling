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
from pdfplumber.utils import extract_text as extract_pdf_chars
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


# Keep this aligned with the existing authored-quiz extraction branch. A few
# stray PDF metadata glyphs must not make an image-only scan look readable.
MIN_READABLE_PDF_TEXT_CHARS = 200

_SUPERSCRIPT_DIGITS = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
_SUBSCRIPT_DIGITS = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

# Standard Adobe Symbol-font character mapping. Some PDFs draw Greek glyphs
# with Latin character codes; pdfminer/pdfplumber otherwise exposes theta as
# "q", phi as "f", etc. Restrict conversion to an actual Symbol font so
# ordinary prose remains untouched.
_SYMBOL_GREEK = {
    "A": "Α", "B": "Β", "C": "Χ", "D": "Δ", "E": "Ε",
    "F": "Φ", "G": "Γ", "H": "Η", "I": "Ι", "K": "Κ",
    "L": "Λ", "M": "Μ", "N": "Ν", "O": "Ο", "P": "Π",
    "Q": "Θ", "R": "Ρ", "S": "Σ", "T": "Τ", "U": "Υ",
    "W": "Ω", "X": "Ξ", "Y": "Ψ", "Z": "Ζ",
    "a": "α", "b": "β", "c": "χ", "d": "δ", "e": "ε",
    "f": "φ", "g": "γ", "h": "η", "i": "ι", "k": "κ",
    "l": "λ", "m": "μ", "n": "ν", "o": "ο", "p": "π",
    "q": "θ", "r": "ρ", "s": "σ", "t": "τ", "u": "υ",
    "w": "ω", "x": "ξ", "y": "ψ", "z": "ζ",
}


@dataclass(frozen=True)
class PageSpan:
    """Approximate page provenance inside the extracted plain-text string."""

    page_number: int
    char_start: int
    char_end: int
    has_images: bool = False


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
            page_text = _extract_pdf_page_text(page)
            start = cursor
            cursor += len(page_text)
            untrimmed_spans.append(PageSpan(page_number, start, cursor, bool(getattr(page, "images", []))))
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
            span.has_images,
        )
        for span in untrimmed_spans
    )
    return ExtractedText(text=text, page_spans=spans)


def require_readable_generation_pages(extracted: ExtractedText) -> None:
    """Reject image-only content instead of silently dropping it in text generation."""
    unreadable = [span.page_number for span in extracted.page_spans
                  if span.has_images and len(extracted.text[span.char_start:span.char_end].strip()) < 40]
    if unreadable:
        pages = ", ".join(str(page) for page in unreadable[:20])
        raise ValueError(f"Pages {pages} contain images with too little readable text for generation. Use an OCR/text-based copy, or Extract Quiz for an existing question paper.")


def _extract_pdf_page_text(page) -> str:
    """Extract one PDF page while preserving common structured notation.

    A slightly wider vertical tolerance keeps raised/lowered glyphs on their
    logical line. Character-level normalization restores Unicode superscript,
    subscript, and Symbol-font Greek glyphs without interpreting the subject.
    """
    raw_chars = getattr(page, "chars", None)
    if not raw_chars:
        try:
            return page.extract_text(y_tolerance=8) or ""
        except TypeError:  # small test doubles and older compatible adapters
            return page.extract_text() or ""

    chars = [dict(char) for char in raw_chars]
    for index, char in enumerate(chars):
        text = str(char.get("text") or "")
        font = str(char.get("fontname") or "").casefold()
        if "symbol" in font and text in _SYMBOL_GREEK:
            char["text"] = _SYMBOL_GREEK[text]
            text = char["text"]

        if len(text) != 1 or text not in "0123456789+-=()" or index == 0:
            continue
        previous = chars[index - 1]
        try:
            adjacent = abs(float(char["x0"]) - float(previous["x1"])) <= 1.5
            smaller = float(char["size"]) < float(previous["size"]) * 0.95
            raised = float(char["top"]) < float(previous["top"]) - 1
            lowered = float(char["top"]) > float(previous["top"]) + 1
        except (KeyError, TypeError, ValueError):
            continue
        if adjacent and smaller and raised:
            char["text"] = text.translate(_SUPERSCRIPT_DIGITS)
        elif adjacent and smaller and lowered:
            char["text"] = text.translate(_SUBSCRIPT_DIGITS)

    return extract_pdf_chars(chars, y_tolerance=8) or ""


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
