"""Universal, one-call, cost-bounded analysis for large typed documents.

Every source location is represented in one compact provider request. A table
of contents or heading is useful when present but is never required. The model
returns navigation groups containing independently selectable topics; exact
evidence is then retrieved locally from the mapped source locations.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.lib.config import get_settings
from app.services.extraction import ExtractedText
from app.services.llm.structured import gemini_json


MAX_INPUT_CHARS = 600_000
MAX_TOPICS = 30
MAX_GROUPS = 12
MAX_CONCEPTS = 10
MAX_RANGES = 4
MAX_EVIDENCE_LOCATIONS = 6
MAX_EXCERPTS_PER_TOPIC = 8
MAX_UNIT_SAMPLE_CHARS = 1_600
MIN_UNIT_SAMPLE_CHARS = 350
CONTENTS_SAMPLE_CHARS = 10_000
SECTION_CHARS = 6_000
EXCERPT_CHARS = 1_000
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+./-]{2,}")
_STOP_WORDS = {
    "and", "are", "for", "from", "into", "layer", "the", "this", "that",
    "with", "using", "overview", "introduction", "principles",
}

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_title": {"type": "string"},
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group_name": {"type": "string"},
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic_name": {"type": "string"},
                                "covered_concepts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_ranges": {
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
                                "evidence_locations": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                            },
                            "required": [
                                "topic_name", "covered_concepts", "source_ranges",
                                "evidence_locations",
                            ],
                        },
                    },
                },
                "required": ["group_name", "topics"],
            },
        },
    },
    "required": ["document_title", "groups"],
}


def _chunk_text(text: str, target_chars: int = SECTION_CHARS) -> dict[int, str]:
    """Split non-paginated formats into stable paragraph-aware source sections."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    units = [
        paragraph[offset : offset + target_chars]
        for paragraph in paragraphs
        for offset in range(0, len(paragraph), target_chars)
    ]
    sections: dict[int, str] = {}
    current = ""
    for paragraph in units:
        candidate = f"{current}\n{paragraph}".strip()
        if current and len(candidate) > target_chars:
            sections[len(sections) + 1] = current
            current = paragraph
        else:
            current = candidate
    if current:
        sections[len(sections) + 1] = current
    if not sections and text.strip():
        sections[1] = text.strip()
    return sections


def _source_locations(extracted: ExtractedText) -> tuple[dict[int, str], str]:
    if extracted.page_spans:
        return (
            {
                span.page_number: extracted.text[span.char_start : span.char_end].strip()
                for span in extracted.page_spans
            },
            "PDF PAGE",
        )
    return _chunk_text(extracted.text), "SOURCE SECTION"


def _sample_text(text: str, budget: int) -> str:
    text = text.strip()
    if len(text) <= budget:
        return text
    tail = min(300, max(80, budget // 4))
    return (
        text[: budget - tail]
        + "\n[... middle omitted for topic discovery ...]\n"
        + text[-tail:]
    )


def _analysis_document(locations: dict[int, str], marker: str) -> str:
    """Represent every location inside a fixed input budget."""
    contents = {
        number
        for number, text in list(locations.items())[:20]
        if "contents" in text[:500].casefold()
    }
    contents_budget = sum(
        min(len(locations[number]), CONTENTS_SAMPLE_CHARS) for number in contents
    )
    ordinary_count = max(1, len(locations) - len(contents))
    marker_budget = len(locations) * 40
    ordinary_budget = max(
        MIN_UNIT_SAMPLE_CHARS,
        min(
            MAX_UNIT_SAMPLE_CHARS,
            (MAX_INPUT_CHARS - contents_budget - marker_budget) // ordinary_count,
        ),
    )
    blocks = []
    for number, text in locations.items():
        budget = CONTENTS_SAMPLE_CHARS if number in contents else ordinary_budget
        blocks.append(f"=== {marker} {number} ===\n{_sample_text(text, budget)}")
    rendered = "\n\n".join(blocks)
    if len(rendered) > MAX_INPUT_CHARS:
        raise ValueError(
            "This document has too many source locations for the one-call safety limit."
        )
    return rendered


def _analyse_once(
    document: str, location_count: int, document_title: str, marker: str
) -> dict:
    settings = get_settings()
    system_prompt = (
        "Organize the supplied teaching material into a universal two-level hierarchy. "
        "Groups are navigation labels only. Topics inside each group are the items a "
        "faculty member can select for quiz generation. Determine the number of groups "
        "and topics from the actual material: a short focused document may have only one "
        "or two topics, while a broad textbook should have many. Do not enforce a minimum. "
        "A selectable topic must be a coherent teachable unit that can support distinct "
        "questions. Do not use an entire broad layer or chapter as one topic when the "
        "material clearly contains independently teachable units, and do not promote "
        "isolated terms, commands, examples, or glossary entries into topics. A contents "
        "page and headings are optional hints, never the sole authority. Use only the "
        "supplied material. Preserve source order where meaningful. Every source range "
        f"and evidence location must refer to an explicit {marker} marker. Some location "
        "middles are omitted only for topic discovery. Do not copy passages into the "
        "response. Return no more than 30 selectable topics overall."
    )
    user_prompt = (
        f"Document name: {document_title or 'Untitled document'}\n"
        f"Source marker: {marker}\n"
        f"Total source locations: {location_count}\n\n"
        f"{document}\n\n"
        "Based on the preceding material, return the groups, independently selectable "
        "topics, covered concepts, inclusive source ranges, and strongest evidence "
        "locations. Do not invent content or location numbers."
    )
    return gemini_json(
        system_prompt,
        user_prompt,
        OUTLINE_SCHEMA,
        model=settings.gemini_blueprint_model,
        temperature=None,
        max_output_tokens=6_000,
        thinking_level="minimal",
        allow_model_fallback=False,
    )


def _bounded_ranges(raw: object, location_count: int) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            start, end = int(item.get("start")), int(item.get("end"))
        except (TypeError, ValueError):
            continue
        start, end = max(1, start), min(location_count, end)
        value = {"start": start, "end": end}
        if start <= end and value not in ranges:
            ranges.append(value)
        if len(ranges) >= MAX_RANGES:
            break
    return ranges


def _inside_ranges(location: int, ranges: list[dict[str, int]]) -> bool:
    return any(item["start"] <= location <= item["end"] for item in ranges)


def _query_terms(name: str, concepts: list[str]) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(" ".join([name, *concepts]))
        if token.casefold() not in _STOP_WORDS
    }


def _ranked_passages(text: str, terms: set[str]) -> list[str]:
    compact = _SPACE.sub(" ", text).strip()
    passages = [
        compact[offset : offset + EXCERPT_CHARS].strip()
        for offset in range(0, len(compact), EXCERPT_CHARS)
        if compact[offset : offset + EXCERPT_CHARS].strip()
    ]
    return sorted(
        passages,
        key=lambda passage: sum(passage.casefold().count(term) for term in terms),
        reverse=True,
    )


def _evidence_excerpts(
    locations: dict[int, str],
    ranges: list[dict[str, int]],
    raw_locations: object,
    *,
    name: str,
    concepts: list[str],
    has_pages: bool,
) -> list[dict]:
    evidence_locations: list[int] = []
    for value in raw_locations if isinstance(raw_locations, list) else []:
        try:
            location = int(value)
        except (TypeError, ValueError):
            continue
        if (
            location in locations
            and _inside_ranges(location, ranges)
            and location not in evidence_locations
        ):
            evidence_locations.append(location)
        if len(evidence_locations) >= MAX_EVIDENCE_LOCATIONS:
            break
    if not evidence_locations:
        evidence_locations = [item["start"] for item in ranges]

    terms = _query_terms(name, concepts)
    excerpts: list[dict] = []
    for location in evidence_locations:
        for passage in _ranked_passages(locations.get(location, ""), terms)[:2]:
            excerpt = {"text": passage}
            if has_pages:
                excerpt.update({"page_start": location, "page_end": location})
            else:
                excerpt.update(
                    {"source_section_start": location, "source_section_end": location}
                )
            excerpts.append(excerpt)
            if len(excerpts) >= MAX_EXCERPTS_PER_TOPIC:
                return excerpts
    return excerpts


def build_single_call_ai_outline(
    extracted: ExtractedText,
    *,
    document_title: str = "",
    analyzer: Callable[[str, int, str, str], dict] | None = None,
    saved_response: dict | None = None,
    response_checkpoint: Callable[[dict], None] | None = None,
) -> dict:
    """Return a source-grounded hierarchy using at most one provider request.

    The raw structured response can be checkpointed before local validation and
    evidence assembly. A retry can then reuse that response if a later local or
    database step failed, avoiding a second paid provider call.
    """
    locations, marker = _source_locations(extracted)
    if not locations:
        raise ValueError("This document has no usable text locations.")
    labelled = _analysis_document(locations, marker)
    if saved_response is not None:
        if not isinstance(saved_response, dict):
            raise ValueError("The saved topic-analysis response is invalid.")
        raw = saved_response
    else:
        raw = (analyzer or _analyse_once)(
            labelled, len(locations), document_title, marker
        )
        if not isinstance(raw, dict):
            raise ValueError("The topic-analysis provider returned an invalid response.")
        if response_checkpoint is not None:
            response_checkpoint(raw)
    has_pages = marker == "PDF PAGE"
    topics: list[dict] = []
    seen: set[str] = set()
    raw_groups = raw.get("groups", []) if isinstance(raw, dict) else []
    for group in raw_groups[:MAX_GROUPS] if isinstance(raw_groups, list) else []:
        if not isinstance(group, dict):
            continue
        group_name = _SPACE.sub(" ", str(group.get("group_name") or "")).strip()
        raw_topics = group.get("topics")
        for item in raw_topics if isinstance(raw_topics, list) else []:
            if not isinstance(item, dict):
                continue
            name = _SPACE.sub(" ", str(item.get("topic_name") or "")).strip()
            key = name.casefold()
            ranges = _bounded_ranges(item.get("source_ranges"), len(locations))
            if not name or key in seen or not ranges:
                continue
            concepts: list[str] = []
            raw_concepts = item.get("covered_concepts")
            for value in raw_concepts if isinstance(raw_concepts, list) else []:
                concept = _SPACE.sub(" ", str(value)).strip()
                if concept and concept.casefold() != key and concept not in concepts:
                    concepts.append(concept)
                if len(concepts) >= MAX_CONCEPTS:
                    break
            excerpts = _evidence_excerpts(
                locations,
                ranges,
                item.get("evidence_locations"),
                name=name,
                concepts=concepts,
                has_pages=has_pages,
            )
            if not excerpts:
                continue
            topics.append(
                {
                    "topic_name": name,
                    "parent_group": group_name or "Other topics",
                    "subtopics": concepts,
                    "key_definitions": [],
                    "key_facts_and_figures": [],
                    "formulas": [],
                    "worked_examples": [],
                    "source_page_ranges": ranges if has_pages else [],
                    "source_section_ranges": [] if has_pages else ranges,
                    "source_excerpts": excerpts,
                }
            )
            seen.add(key)
            if len(topics) >= MAX_TOPICS:
                break
        if len(topics) >= MAX_TOPICS:
            break

    if not topics:
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
            "source_location_count": len(locations),
            "source_marker": marker,
        },
    }
