"""Deterministic outline extraction for well-structured, typed PDFs.

This is deliberately confidence-gated.  A PDF must expose a usable page map and
an early index/table-of-contents page with several increasing page references.
When those signals are absent, callers keep the existing AI Map-Reduce path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches

from app.services.extraction import ExtractedText


_INDEX_MARKERS = ("INDEX", "CONTENTS", "TABLE OF CONTENTS")
_UNIT_HEADING = re.compile(
    r"^UNIT\s*[-: ]*([IVXLCDM]+|\d+)\s*:?[ \t]*$", re.IGNORECASE
)
_STANDALONE_ROMAN = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
_PAGE_ENTRY = re.compile(r"^(.*?\D)\s+(\d{1,4})\s*$")
_LEADING_UNIT = re.compile(r"^(?:UNIT\s+)?[IVXLCDM]+\s+", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class OutlineEntry:
    title: str
    logical_page: int


def _page_texts(extracted: ExtractedText) -> list[str]:
    return [
        extracted.text[span.char_start : span.char_end].strip()
        for span in extracted.page_spans
    ]


def _clean_title(value: str) -> str:
    value = re.sub(r"(?<=[A-Za-z]),(?=[A-Za-z])", " ", value)
    value = _LEADING_UNIT.sub("", _SPACE.sub(" ", value)).strip(" -:;,.\t")
    # Keep familiar acronyms readable while normalising shouty index entries.
    words = []
    for word in value.split():
        bare = word.strip("(),")
        if bare.upper() in {
            "OSI", "TCP", "IP", "TCP/IP", "UDP", "HTTP", "DNS", "WWW", "RSA"
        }:
            words.append(bare.upper())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def _repair_title_from_front_matter(title: str, front_matter: str) -> str:
    """Repair obvious index OCR/typing glitches using words already in the PDF."""
    title = re.sub(r"(?<=[A-Za-z]),(?=[A-Za-z])", " ", title)
    vocabulary: dict[str, str] = {}
    for word in re.findall(r"[A-Za-z]{3,}", front_matter):
        vocabulary.setdefault(word.casefold(), word)
    tokens = title.split()
    repaired: list[str] = []
    index = 0
    while index < len(tokens):
        raw = tokens[index]
        token = re.sub(r"[^A-Za-z]", "", raw)
        if index + 1 < len(tokens):
            next_token = re.sub(r"[^A-Za-z]", "", tokens[index + 1])
            joined = (token + next_token).casefold()
            if len(joined) >= 5 and joined in vocabulary:
                repaired.append(vocabulary[joined])
                index += 2
                continue
        folded = token.casefold()
        if len(token) >= 5 and folded not in vocabulary:
            matches = get_close_matches(folded, vocabulary, n=1, cutoff=0.82)
            if matches:
                repaired.append(vocabulary[matches[0]])
                index += 1
                continue
        repaired.append(raw)
        index += 1
    return _clean_title(" ".join(repaired))


def _index_entries(pages: list[str]) -> tuple[list[OutlineEntry], int] | None:
    """Return increasing index entries and the zero-based index page."""
    for page_index, page in enumerate(pages[:20]):
        upper = page.upper()
        if not any(marker in upper for marker in _INDEX_MARKERS) or "PAGE" not in upper:
            continue
        raw_entries: list[tuple[str, int]] = []
        for raw_line in page.splitlines():
            line = _SPACE.sub(" ", raw_line).strip()
            match = _PAGE_ENTRY.match(line)
            if match:
                title = _LEADING_UNIT.sub("", match.group(1)).strip(" -:;,.\t")
                logical_page = int(match.group(2))
                if len(title) < 4 or logical_page < 1:
                    continue
                if raw_entries and logical_page <= raw_entries[-1][1]:
                    continue
                raw_entries.append((title, logical_page))
                continue

            # Index entries often wrap onto the next line after the page number.
            # Append short uppercase continuations, ignoring standalone unit labels.
            if (
                not raw_entries
                or not line
                or _UNIT_HEADING.fullmatch(line)
                or _STANDALONE_ROMAN.fullmatch(line)
            ):
                continue
            continuation = _LEADING_UNIT.sub("", line).strip(" -:;,.\t")
            letters = [char for char in continuation if char.isalpha()]
            if not continuation or not letters or len(continuation.split()) > 4:
                continue
            uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
            if uppercase_ratio >= 0.85 and continuation.upper() not in {
                "INDEX", "UNIT NO", "TOPIC", "PAGE NO"
            }:
                title, logical_page = raw_entries[-1]
                raw_entries[-1] = (f"{title} {continuation}", logical_page)

        # Exclude the noisy index itself; syllabus/front-matter text is the
        # correction source for misspelled or split index words.
        front_matter = "\n".join(pages[:page_index])
        entries = [
            OutlineEntry(
                title=_repair_title_from_front_matter(title, front_matter),
                logical_page=logical_page,
            )
            for title, logical_page in raw_entries
        ]
        if len(entries) >= 6:
            return entries, page_index
    return None


def _physical_page_offset(
    pages: list[str], entries: list[OutlineEntry], index_page: int
) -> int | None:
    """Map printed index pages to physical PDF pages.

    Academic notes commonly place title/syllabus/index pages before printed page
    1.  Prefer the first standalone UNIT heading after the index, which is a much
    stronger signal than a fuzzy body-text match.
    """
    first_logical = entries[0].logical_page
    for page_index in range(index_page + 1, min(len(pages), index_page + 40)):
        lines = [line.strip() for line in pages[page_index].splitlines() if line.strip()]
        if lines and _UNIT_HEADING.fullmatch(lines[0]):
            return (page_index + 1) - first_logical

    # Fallback for books without UNIT labels: require at least two meaningful
    # title words near the top of a page.
    title_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z]{4,}", entries[0].title)
        if token.casefold() not in {"introduction", "overview"}
    }
    if not title_tokens:
        return None
    for page_index in range(index_page + 1, min(len(pages), index_page + 50)):
        heading = " ".join(pages[page_index].splitlines()[:12]).casefold()
        matches = sum(token in heading for token in title_tokens)
        if matches >= min(2, len(title_tokens)):
            return (page_index + 1) - first_logical
    return None


def _evidence_segments(page_text: str, *, target_chars: int = 700) -> list[str]:
    """Create compact, exact-page evidence blocks without an AI call."""
    text = _SPACE.sub(" ", page_text).strip()
    if len(text) < 40:
        return []
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    if not sentences:
        return [text]
    blocks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > target_chars:
            blocks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def _heading_previews(page_texts: list[str], *, limit: int = 16) -> list[str]:
    previews: list[str] = []
    seen: set[str] = set()
    for page in page_texts:
        for raw_line in page.splitlines()[:18]:
            line = _SPACE.sub(" ", raw_line).strip(" -:;\t")
            words = line.split()
            if not (2 <= len(words) <= 10) or not (5 <= len(line) <= 80):
                continue
            letters = [char for char in line if char.isalpha()]
            if not letters:
                continue
            uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
            if uppercase_ratio < 0.82 or _UNIT_HEADING.fullmatch(line):
                continue
            if line.casefold().startswith(("figure ", "table ", "example ")):
                continue
            cleaned = _clean_title(line)
            key = cleaned.casefold()
            if key and key not in seen:
                previews.append(cleaned)
                seen.add(key)
                if len(previews) >= limit:
                    return previews
    return previews


def build_local_pdf_outline(extracted: ExtractedText) -> dict | None:
    """Build a page-grounded Master Blueprint without any provider call.

    Returns ``None`` when the structure is not reliable enough.  That fail-closed
    behaviour is what makes it safe to keep AI analysis as the fallback.
    """
    if len(extracted.page_spans) < 8:
        return None
    pages = _page_texts(extracted)
    parsed = _index_entries(pages)
    if not parsed:
        return None
    entries, index_page = parsed
    offset = _physical_page_offset(pages, entries, index_page)
    if offset is None:
        return None

    physical_starts = [entry.logical_page + offset for entry in entries]
    if (
        physical_starts[0] <= index_page + 1
        or physical_starts[-1] > len(pages)
        or any(a >= b for a, b in zip(physical_starts, physical_starts[1:]))
    ):
        return None

    topics: list[dict] = []
    for index, (entry, page_start) in enumerate(zip(entries, physical_starts)):
        page_end = (
            physical_starts[index + 1] - 1
            if index + 1 < len(physical_starts)
            else len(pages)
        )
        if page_end < page_start:
            return None
        selected_pages = pages[page_start - 1 : page_end]
        excerpts = [
            {
                "text": segment,
                "page_start": page_number,
                "page_end": page_number,
            }
            for page_number, page_text in enumerate(selected_pages, start=page_start)
            for segment in _evidence_segments(page_text)
        ]
        if not excerpts:
            return None
        topics.append(
            {
                "topic_name": entry.title,
                "subtopics": _heading_previews(selected_pages),
                "key_definitions": [],
                "key_facts_and_figures": [],
                "formulas": [],
                "worked_examples": [],
                "source_excerpts": excerpts,
                "source_page_ranges": [{"start": page_start, "end": page_end}],
            }
        )

    return {
        "analysis_mode": "local_typed_pdf_outline",
        "source_topic_count": len(topics),
        "topics": topics,
        "local_outline": {
            "index_page": index_page + 1,
            "printed_to_physical_page_offset": offset,
            "provider_calls": 0,
        },
    }
