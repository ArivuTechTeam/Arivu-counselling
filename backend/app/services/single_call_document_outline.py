"""One-call, cost-bounded topic analysis for large typed PDFs.

The provider sees the page-labelled text once and returns only a compact topic
hierarchy and page references. Exact source evidence is then copied locally
from those pages, so no model output tokens are wasted repeating the document.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.lib.config import get_settings
from app.services.extraction import ExtractedText
from app.services.llm.structured import gemini_json


# Stay comfortably below the free-tier 250k-token/minute ceiling and keep paid
# input cost predictable. Large books are represented by a structure-preserving
# sample from every page rather than blindly sending every paragraph.
MAX_INPUT_CHARS = 600_000
PAGE_SAMPLE_CHARS = 1_600
PAGE_SAMPLE_TAIL_CHARS = 400
MAX_TOPICS = 24
MAX_SUBTOPICS = 12
MAX_RANGES = 4
MAX_EVIDENCE_PAGES = 6
MAX_EXCERPTS_PER_TOPIC = 8
EXCERPT_CHARS = 1_200
_SPACE = re.compile(r"\s+")

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_name": {"type": "string"},
                    "subtopics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "page_ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "integer"},
                                "end": {"type": "integer"},
                            },
                            "required": ["start", "end"],
                        },
                    },
                    "evidence_pages": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": [
                    "topic_name",
                    "subtopics",
                    "page_ranges",
                    "evidence_pages",
                ],
            },
        },
    },
    "required": ["document_title", "topics"],
}


def _page_texts(extracted: ExtractedText) -> dict[int, str]:
    return {
        span.page_number: extracted.text[span.char_start : span.char_end].strip()
        for span in extracted.page_spans
    }


def _labelled_document(pages: dict[int, str]) -> str:
    return "\n\n".join(
        f"=== PDF PAGE {number} ===\n{text}" for number, text in pages.items()
    )


def _analysis_document(pages: dict[int, str]) -> str:
    """Keep every page represented while bounding provider input tokens.

    Front matter contents pages are retained in full because they carry the
    hierarchy. Other long pages contribute their beginning and ending, which
    captures chapter/section headings and page transitions without paying to
    send every explanatory paragraph during topic discovery.
    """
    sampled: dict[int, str] = {}
    for number, text in pages.items():
        compact = text.strip()
        is_contents = number <= 20 and "contents" in compact[:500].casefold()
        if not is_contents and len(compact) > PAGE_SAMPLE_CHARS:
            head_chars = PAGE_SAMPLE_CHARS - PAGE_SAMPLE_TAIL_CHARS
            compact = (
                compact[:head_chars]
                + "\n[... middle of page omitted for topic discovery ...]\n"
                + compact[-PAGE_SAMPLE_TAIL_CHARS:]
            )
        sampled[number] = compact
    return _labelled_document(sampled)


def _analyse_once(document: str, page_count: int, document_title: str) -> dict:
    settings = get_settings()
    system_prompt = (
        "You organize teaching material into a concise, faculty-friendly syllabus. "
        "Use only the supplied page samples. Return major teachable topics, not isolated "
        "terms, commands, examples, or glossary entries. Merge related concepts under "
        "one major topic. Preserve the order of the source. Page numbers must refer to "
        "the explicit PDF PAGE markers. Some page middles are intentionally omitted; "
        "infer no facts from an omission marker. Return 12-24 major topics when the material "
        "supports them, with at most 12 concise subtopics each. Choose up to 6 evidence "
        "pages per topic that contain the strongest explanatory material. Do not copy "
        "source passages into the response."
    )
    user_prompt = (
        f"Document name: {document_title or 'Untitled document'}\n"
        f"Total PDF pages: {page_count}\n\n"
        "Build the topic hierarchy and map every topic to its inclusive page ranges. "
        "Do not invent topics or page numbers.\n\n"
        f"{document}"
    )
    return gemini_json(
        system_prompt,
        user_prompt,
        OUTLINE_SCHEMA,
        model=settings.gemini_blueprint_model,
        temperature=None,
        max_output_tokens=6_000,
        thinking_level="minimal",
        # A missing Flash-Lite model must fail visibly, not retry the more
        # expensive full Flash model and break the one-call cost guarantee.
        allow_model_fallback=False,
    )


def _bounded_ranges(raw: object, page_count: int) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            start, end = int(item.get("start")), int(item.get("end"))
        except (TypeError, ValueError):
            continue
        start, end = max(1, start), min(page_count, end)
        if start <= end:
            ranges.append({"start": start, "end": end})
        if len(ranges) >= MAX_RANGES:
            break
    return ranges


def _inside_ranges(page: int, ranges: list[dict[str, int]]) -> bool:
    return any(item["start"] <= page <= item["end"] for item in ranges)


def _evidence_excerpts(
    pages: dict[int, str], ranges: list[dict[str, int]], raw_pages: object
) -> list[dict]:
    evidence_pages: list[int] = []
    for value in raw_pages if isinstance(raw_pages, list) else []:
        try:
            page = int(value)
        except (TypeError, ValueError):
            continue
        if page in pages and _inside_ranges(page, ranges) and page not in evidence_pages:
            evidence_pages.append(page)
        if len(evidence_pages) >= MAX_EVIDENCE_PAGES:
            break
    if not evidence_pages:
        evidence_pages = [item["start"] for item in ranges[:MAX_EVIDENCE_PAGES]]

    excerpts: list[dict] = []
    for page in evidence_pages:
        text = _SPACE.sub(" ", pages.get(page, "")).strip()
        for offset in range(0, min(len(text), EXCERPT_CHARS * 2), EXCERPT_CHARS):
            excerpt = text[offset : offset + EXCERPT_CHARS].strip()
            if len(excerpt) >= 80:
                excerpts.append(
                    {"text": excerpt, "page_start": page, "page_end": page}
                )
            if len(excerpts) >= MAX_EXCERPTS_PER_TOPIC:
                return excerpts
    return excerpts


def build_single_call_ai_outline(
    extracted: ExtractedText,
    *,
    document_title: str = "",
    analyzer: Callable[[str, int, str], dict] | None = None,
) -> dict:
    """Return a validated page-grounded blueprint using exactly one AI request."""
    pages = _page_texts(extracted)
    if not pages:
        raise ValueError("One-call analysis requires a PDF with page information.")
    labelled = _analysis_document(pages)
    if len(labelled) > MAX_INPUT_CHARS:
        raise ValueError(
            "This PDF exceeds the one-call cost limit. Split it into smaller volumes."
        )

    raw = (analyzer or _analyse_once)(labelled, len(pages), document_title)
    topics: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("topics", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        name = _SPACE.sub(" ", str(item.get("topic_name") or "")).strip()
        key = name.casefold()
        ranges = _bounded_ranges(item.get("page_ranges"), len(pages))
        if not name or key in seen or not ranges:
            continue
        subtopics = []
        for value in item.get("subtopics", []) if isinstance(item.get("subtopics"), list) else []:
            subtopic = _SPACE.sub(" ", str(value)).strip()
            if subtopic and subtopic.casefold() != key and subtopic not in subtopics:
                subtopics.append(subtopic)
            if len(subtopics) >= MAX_SUBTOPICS:
                break
        excerpts = _evidence_excerpts(pages, ranges, item.get("evidence_pages"))
        if not excerpts:
            continue
        topics.append(
            {
                "topic_name": name,
                "subtopics": subtopics,
                "key_definitions": [],
                "key_facts_and_figures": [],
                "formulas": [],
                "worked_examples": [],
                "source_page_ranges": ranges,
                "source_excerpts": excerpts,
            }
        )
        seen.add(key)
        if len(topics) >= MAX_TOPICS:
            break

    if len(topics) < 3:
        raise ValueError("The one-call analysis did not return a usable topic outline.")
    return {
        "document_title": str(raw.get("document_title") or document_title).strip(),
        "analysis_mode": "single_call_ai_outline",
        "source_topic_count": len(topics),
        "topics": topics,
        "single_call_outline": {
            "provider_calls": 1,
            "model": get_settings().gemini_blueprint_model,
            "input_characters": len(labelled),
            "source_characters": len(extracted.text),
            "page_count": len(pages),
        },
    }
