"""
Text extraction from uploaded documents.

Slice 2 supports the two text-based formats from the scoping doc:
  - PDF  -> pdfplumber
  - DOCX -> python-docx

Scanned/image-only PDFs (which need Tesseract OCR) are intentionally out of
scope for now. A PDF that is just scanned images will extract little or no text;
the caller sees that via a near-zero character count.
"""

from __future__ import annotations

import io

import pdfplumber
from docx import Document


def extract_text(content: bytes, ext: str) -> str:
    """Extract plain text from a document's bytes, chosen by file extension."""
    ext = ext.lower()
    if ext == "pdf":
        return _extract_pdf(content)
    if ext == "docx":
        return _extract_docx(content)
    raise ValueError(f"Unsupported file type: .{ext}")


def _extract_pdf(content: bytes) -> str:
    # io.BytesIO wraps the in-memory bytes so pdfplumber can read them like a file.
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n\n".join(parts).strip()


def _extract_docx(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs).strip()
