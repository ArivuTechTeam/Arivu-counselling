"""Helpers for rendering and matching source material with page provenance."""

from __future__ import annotations

import re

from app.services.extraction import ExtractedText


_PDF_PAGE = re.compile(r"^=== SOURCE PAGE (\d+) ===$", re.MULTILINE)
_BLUEPRINT_RANGE = re.compile(
    r"^Approximate source pages:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
_RANGE = re.compile(r"(\d+)\s*-\s*(\d+)")
_EXPLICIT_EXCERPT = re.compile(r'^- Source excerpt:\s*"(.+)"$', re.MULTILINE)
_SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUBSCRIPT_TRANSLATION = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_FORMULA_OPERATORS = re.compile(r"[=<>≤≥+−*/×÷^√∑∫²³₀-₉]")


def render_extracted_material(
    extracted: ExtractedText,
    *,
    start: int = 0,
    max_chars: int | None = None,
) -> str:
    """Render an extracted document while keeping lightweight PDF page markers.

    DOCX has no stable page map, so its text is returned unchanged. The character
    ceiling applies to source text, not to the inserted marker labels.
    """
    end = len(extracted.text) if max_chars is None else min(
        len(extracted.text), start + max_chars
    )
    if not extracted.page_spans:
        return extracted.text[start:end]

    parts: list[str] = []
    for span in extracted.page_spans:
        part_start = max(start, span.char_start)
        part_end = min(end, span.char_end)
        if part_start >= part_end:
            continue
        body = extracted.text[part_start:part_end].strip()
        if body:
            parts.append(f"=== SOURCE PAGE {span.page_number} ===\n{body}")
    return "\n\n".join(parts).strip()


def normalise_evidence(value: str) -> str:
    """Whitespace/case normalisation used for deterministic excerpt matching."""
    return " ".join(value.split()).casefold()


def normalise_symbolic_evidence(value: str) -> str:
    """Normalise notation for matching while preserving the displayed source."""
    value = value.translate(_SUPERSCRIPT_TRANSLATION).translate(_SUBSCRIPT_TRANSLATION)
    value = value.replace("−", "-").replace("×", "*").replace("÷", "/")
    value = value.replace("·", "*").replace("½", "1/2")
    # Keep hard line boundaries so the last token on one line cannot be joined
    # to the first token on the next and mistaken for one larger formula.
    value = re.sub(r"[\r\n]+", "|", value)
    return re.sub(r"[\t\f\v ]+", "", value).casefold()


def is_symbolic_evidence(value: str) -> bool:
    """Recognise compact equations, chemical notation, and code as evidence."""
    compact = normalise_symbolic_evidence(value)
    if len(compact) < 3 or not re.search(r"[a-z0-9]", compact):
        return False
    if _FORMULA_OPERATORS.search(value):
        return True
    return bool(
        re.search(r"\b(def|return|select|from|where|class|function)\b", value, re.I)
        or "=>" in value
        or "->" in value
    )


def is_meaningful_evidence(value: str) -> bool:
    """Use prose length rules only for prose—not complete symbolic evidence."""
    if is_symbolic_evidence(value):
        return True
    words = re.findall(r"\w+", value, flags=re.UNICODE)
    return len(words) >= 4 and len(normalise_evidence(value)) >= 20


def evidence_occurs_in_material(evidence: str, material: str) -> bool:
    symbolic = is_symbolic_evidence(evidence)
    if not symbolic and normalise_evidence(evidence) in normalise_evidence(material):
        return True
    if not symbolic:
        return False
    needle = normalise_symbolic_evidence(evidence)
    haystack = normalise_symbolic_evidence(material)
    start = 0
    while (index := haystack.find(needle, start)) >= 0:
        before = haystack[index - 1] if index else ""
        end = index + len(needle)
        after = haystack[end] if end < len(haystack) else ""
        # A compact formula must not verify merely because it is a prefix of a
        # different token (for example, mv must not match mv2 and H2O must not
        # match H2O2). Punctuation and surrounding prose remain valid bounds.
        if not before.isalnum() and not after.isalnum():
            return True
        start = index + 1
    return False


def material_page_ranges(material: str) -> list[tuple[int, int]]:
    """Return every explicit page/range label present in rendered material."""
    ranges = [(int(page), int(page)) for page in _PDF_PAGE.findall(material)]
    for raw in _BLUEPRINT_RANGE.findall(material):
        ranges.extend((int(start), int(end)) for start, end in _RANGE.findall(raw))
    return sorted(set(ranges))


def explicit_source_excerpts(material: str) -> list[str]:
    """Return consolidated excerpts that were checked against original chunks."""
    return [match.strip() for match in _EXPLICIT_EXCERPT.findall(material) if match.strip()]


def page_range_is_available(
    material: str,
    page_start: int | None,
    page_end: int | None,
    *,
    excerpt: str | None = None,
) -> bool:
    """Validate a claimed page range when the source has page metadata.

    Sources without page metadata (notably DOCX) legitimately use null pages.
    """
    available = evidence_page_ranges(material, excerpt) if excerpt else []
    if not available:
        available = material_page_ranges(material)
    if not available:
        return page_start is None and page_end is None
    if page_start is None or page_end is None or page_start < 1 or page_end < page_start:
        return False
    return any(start <= page_start and page_end <= end for start, end in available)


def evidence_page_ranges(material: str, excerpt: str | None) -> list[tuple[int, int]]:
    """Find page labels attached to the block containing an evidence excerpt."""
    needle = normalise_evidence(excerpt or "")
    if not needle:
        return []

    found: list[tuple[int, int]] = []
    page_matches = list(_PDF_PAGE.finditer(material))
    for index, match in enumerate(page_matches):
        block_end = page_matches[index + 1].start() if index + 1 < len(page_matches) else len(material)
        if needle in normalise_evidence(material[match.end() : block_end]):
            page = int(match.group(1))
            found.append((page, page))

    topic_starts = list(re.finditer(r"^##\s+.+$", material, re.MULTILINE))
    for index, match in enumerate(topic_starts):
        block_end = topic_starts[index + 1].start() if index + 1 < len(topic_starts) else len(material)
        block = material[match.start() : block_end]
        if needle not in normalise_evidence(block):
            continue
        for raw in _BLUEPRINT_RANGE.findall(block):
            found.extend((int(start), int(end)) for start, end in _RANGE.findall(raw))
    return sorted(set(found))
