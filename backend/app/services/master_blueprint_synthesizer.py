"""
MasterBlueprintSynthesizer — the REDUCE phase of large-document quiz generation.

MAP produced rich, verbatim study content per chunk, but with duplicates: the
chunks overlap, and the same topic can span several of them. REDUCE is a single
LLM call that semantically merges all of that into ONE clean, de-duplicated
Master Blueprint — the single source the final generation call (Phase 6) writes
questions from.

Why the merge is done by the model, not code: deciding that "Slicing strings"
and "String indexing & slicing" are the same topic, or that two differently-worded
definitions say the same thing, is a semantic judgement. Byte-level dedup already
happened earlier (SHA-256 in the chunk store); this is the meaning-level dedup.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.llm.base import LLMError
from app.services.llm.structured import complete_json_large
from app.services.ai_call_logging import ai_call_context
from app.services.map_reduce_prompts import REDUCE_SYSTEM, build_reduce_user_prompt
from app.services.rate_limit import TOPIC_EXTRACTION, enforce_ai_rate_limit
from app.services.source_material import evidence_occurs_in_material

logger = logging.getLogger(__name__)


_LIST_FIELDS = (
    "subtopics",
    "key_definitions",
    "key_facts_and_figures",
    "formulas",
    "worked_examples",
    "source_excerpts",
    "source_page_ranges",
)


def _stable_unique(items: list, *, key) -> list:
    """Keep reading order while removing exact/normalised overlap duplicates."""
    seen: set[str] = set()
    result: list = []
    for item in items:
        marker = key(item)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _item_key(item: object) -> str:
    if isinstance(item, str):
        return _word_stream(item)
    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=False, sort_keys=True).casefold()
    return str(item).casefold()


def _name_tokens(value: str) -> set[str]:
    return {
        token[:-1] if token.endswith("s") and len(token) > 3 else token
        for token in _word_stream(value).split()
        if len(token) > 1
    }


def _supported_group_name(candidate: str, sources: list[dict]) -> str:
    """Reject a reduce-stage label that broadens beyond every mapped topic."""
    candidate_tokens = _name_tokens(candidate)
    if candidate_tokens:
        supported_tokens: set[str] = set()
        for source in sources:
            source_tokens = _name_tokens(str(source.get("topic_name") or ""))
            supported_tokens.update(source_tokens)
            for subtopic in source.get("subtopics") or []:
                supported_tokens.update(_name_tokens(str(subtopic)))
            for definition in source.get("key_definitions") or []:
                if isinstance(definition, dict):
                    supported_tokens.update(
                        _name_tokens(str(definition.get("term") or ""))
                    )
            for formula in source.get("formulas") or []:
                if isinstance(formula, dict):
                    supported_tokens.update(
                        _name_tokens(str(formula.get("name") or ""))
                    )
            if len(candidate_tokens & source_tokens) / len(candidate_tokens) >= 0.67:
                return candidate
        # A parent label may be supported collectively by the mapped hierarchy
        # even when no single micro-topic contains every word in that label.
        if len(candidate_tokens & supported_tokens) / len(candidate_tokens) >= 0.67:
            return candidate
    return str(sources[0].get("topic_name") or "Untitled topic").strip()


def _distinct_source_topic_names(sources: list[dict], merged_name: str) -> list[str]:
    """Keep original concept labels when a reduce plan over-groups topics.

    Exact and word-order variants are one concept ("String slicing" and
    "Slicing strings"). Genuinely different names remain available as child
    choices even if the model places them under a broad parent.
    """
    merged_tokens = _name_tokens(merged_name)
    seen_token_sets: set[frozenset[str]] = set()
    names: list[str] = []
    for source in sources:
        source_name = " ".join(str(source.get("topic_name") or "").split())
        tokens = frozenset(_name_tokens(source_name))
        if not source_name or not tokens or tokens in seen_token_sets:
            continue
        seen_token_sets.add(tokens)
        if tokens == frozenset(merged_tokens):
            continue
        names.append(source_name)
    return names


def build_topic_catalogue(topics: list[dict]) -> list[dict]:
    """Create the small payload the model needs for semantic topic grouping.

    The large verbatim fields remain server-side and therefore never need to be
    generated again by the model.
    """
    catalogue: list[dict] = []
    for index, topic in enumerate(topics, start=1):
        catalogue.append(
            {
                "source_topic_id": f"T{index:04d}",
                "topic_name": str(topic.get("topic_name") or "").strip(),
                "subtopics": (topic.get("subtopics") or [])[:20],
                "definition_terms": [
                    str(item.get("term") or "").strip()
                    for item in (topic.get("key_definitions") or [])
                    if isinstance(item, dict) and str(item.get("term") or "").strip()
                ][:20],
                "formula_names": [
                    str(item.get("name") or item.get("formula") or "").strip()
                    for item in (topic.get("formulas") or [])
                    if isinstance(item, dict)
                    and str(item.get("name") or item.get("formula") or "").strip()
                ][:20],
                "source_page_ranges": topic.get("source_page_ranges") or [],
            }
        )
    return catalogue


def apply_merge_plan(topics: list[dict], plan: object) -> list[dict]:
    """Apply an LLM semantic plan without letting it rewrite source evidence.

    Unknown/duplicate ids are ignored. Any id the model forgets is retained as a
    standalone topic, preventing a malformed or truncated plan from silently
    dropping document content.
    """
    if not isinstance(plan, dict):
        raise LLMError("Blueprint consolidation returned an invalid merge plan.")
    groups = plan.get("topic_groups")
    if not isinstance(groups, list):
        raise LLMError("Blueprint consolidation omitted topic_groups.")

    indexed = {f"T{index:04d}": topic for index, topic in enumerate(topics, start=1)}
    discarded = {
        value
        for value in (plan.get("discarded_source_topic_ids") or [])
        if isinstance(value, str) and value in indexed
    }
    used: set[str] = set()
    merged_with_order: list[tuple[int, dict]] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        ids = [
            value
            for value in (group.get("source_topic_ids") or [])
            if isinstance(value, str)
            and value in indexed
            and value not in used
            and value not in discarded
        ]
        if not ids:
            continue
        used.update(ids)
        sources = [indexed[value] for value in ids]
        name = str(group.get("topic_name") or "").strip()
        if not name:
            name = str(sources[0].get("topic_name") or "Untitled topic").strip()
        else:
            name = _supported_group_name(name, sources)
        merged: dict = {"topic_name": name}
        if len(sources) > 1:
            source_names = _distinct_source_topic_names(sources, "")
            if len(source_names) > 1:
                # Retain the original labels explicitly. This is both an audit
                # trail and a deterministic escape hatch when REDUCE groups
                # different assessable concepts under one broad label.
                merged["source_topic_names"] = source_names
        for field in _LIST_FIELDS:
            values = [item for source in sources for item in (source.get(field) or [])]
            if field == "subtopics" and len(sources) > 1:
                values = _distinct_source_topic_names(sources, name) + values
            if field == "source_page_ranges":
                values = sorted(
                    _stable_unique(values, key=_item_key),
                    key=lambda value: (value.get("start", 0), value.get("end", 0)),
                )
            else:
                values = _stable_unique(values, key=_item_key)
            merged[field] = values
        first_index = min(int(value[1:]) for value in ids)
        merged_with_order.append((first_index, merged))

    # Fail safe: preserve anything not explicitly grouped or discarded.
    for source_id, source in indexed.items():
        if source_id in used or source_id in discarded:
            continue
        preserved = {"topic_name": str(source.get("topic_name") or "Untitled topic")}
        for field in _LIST_FIELDS:
            preserved[field] = _stable_unique(list(source.get(field) or []), key=_item_key)
        merged_with_order.append((int(source_id[1:]), preserved))

    merged_with_order.sort(key=lambda item: item[0])
    return [topic for _order, topic in merged_with_order]


def _word_stream(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def _fact_matches_source(fact: str, source: str) -> bool:
    """Accept when any meaningful six-word fact window is present verbatim."""
    fact_words = _word_stream(fact).split()
    source_words = _word_stream(source)
    if len(fact_words) < 3:
        return False
    width = min(6, len(fact_words))
    return any(
        " ".join(fact_words[index : index + width]) in source_words
        for index in range(len(fact_words) - width + 1)
    )


def spot_check_verbatim_facts(
    topics: list[dict], chunks: list[dict], *, sample_size: int = 5
) -> dict:
    """Check a deterministic small sample without blocking consolidation."""
    checked = 0
    matched = 0
    for topic in topics:
        ranges = topic.get("source_page_ranges") or []
        attributed = [
            chunk
            for chunk in chunks
            if not ranges
            or chunk.get("page_start") is None
            or any(
                int(r.get("end", 0)) >= int(chunk.get("page_start") or 0)
                and int(r.get("start", 0)) <= int(chunk.get("page_end") or 0)
                for r in ranges
                if isinstance(r, dict)
            )
        ]
        source = "\n".join(str(chunk.get("content") or "") for chunk in attributed)
        for fact_index, fact in enumerate(topic.get("key_facts_and_figures") or []):
            if checked >= sample_size:
                break
            checked += 1
            if _fact_matches_source(str(fact), source):
                matched += 1
            else:
                logger.warning(
                    "Consolidated fact failed verbatim spot-check "
                    "(topic=%s, fact_index=%d, source_ranges=%s)",
                    str(topic.get("topic_name") or "")[:120],
                    fact_index,
                    ranges,
                )
        if checked >= sample_size:
            break
    return {"checked": checked, "matched": matched, "warnings": checked - matched}


def keep_verified_source_excerpts(topics: list[dict], chunks: list[dict]) -> int:
    """Drop reduce-stage excerpts that cannot be found in attributed raw chunks."""
    dropped = 0
    for topic in topics:
        ranges = topic.get("source_page_ranges") or []
        attributed = [
            chunk
            for chunk in chunks
            if not ranges
            or chunk.get("page_start") is None
            or any(
                int(r.get("end", 0)) >= int(chunk.get("page_start") or 0)
                and int(r.get("start", 0)) <= int(chunk.get("page_end") or 0)
                for r in ranges
                if isinstance(r, dict)
            )
        ]
        source = "\n".join(str(chunk.get("content") or "") for chunk in attributed)
        kept = []
        for excerpt in topic.get("source_excerpts") or []:
            text = str(excerpt.get("text") or "").strip()
            if text and evidence_occurs_in_material(text, source):
                kept.append(excerpt)
            else:
                dropped += 1
        topic["source_excerpts"] = kept
    if dropped:
        logger.warning("Dropped %d consolidated source excerpts not found verbatim.", dropped)
    return dropped


class MasterBlueprintSynthesizer:
    def __init__(self, service=None) -> None:
        self._service = service  # injectable for tests

    def _collect_chunks(self, *, document_id: str, tenant_id: str) -> list[dict]:
        client = self._service or get_service_client()
        rows = (
            client.table("document_chunks")
            .select(
                "chunk_index, map_status, topics_json, content, page_start, page_end"
            )
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .order("chunk_index")
            .execute()
            .data
            or []
        )
        return [
            row
            for row in sorted(rows, key=lambda r: r["chunk_index"])
            if row.get("map_status") == "succeeded"
        ]

    def _collect_topics(self, *, document_id: str, tenant_id: str) -> list[dict]:
        """Flatten the topics from every SUCCEEDED chunk, in reading order."""
        topics: list[dict] = []
        for row in self._collect_chunks(document_id=document_id, tenant_id=tenant_id):
            topics.extend((row.get("topics_json") or {}).get("topics", []) or [])
        return topics

    def _reduce(
        self,
        *,
        document_id: str,
        tenant_id: str,
        document_title: str,
        topics: list[dict],
        document_summary: str = "",
        profile: CurrentProfile | None = None,
    ) -> list[dict]:
        """One LLM call to merge/de-duplicate, retrying once on a transient error."""
        catalogue = build_topic_catalogue(topics)
        user = build_reduce_user_prompt(
            document_title=document_title,
            topics_json=json.dumps(catalogue, ensure_ascii=False),
            document_summary=document_summary,
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if profile is not None:
                    enforce_ai_rate_limit(
                        profile=profile,
                        endpoint=TOPIC_EXTRACTION,
                        hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
                        action_label="large-document analysis",
                    )
                with ai_call_context(
                    "topic_extraction_reduce", tenant_id=tenant_id, document_id=document_id
                ):
                    data, _provider = complete_json_large(REDUCE_SYSTEM, user)
                return apply_merge_plan(topics, data)
            except (LLMError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "Blueprint consolidation attempt %d of 2 failed: %s",
                    attempt + 1,
                    exc,
                )
        raise last_error or LLMError("Blueprint synthesis failed.")

    def synthesize(
        self,
        *,
        document_id: str,
        tenant_id: str,
        document_title: str = "",
        document_summary: str = "",
        profile: CurrentProfile | None = None,
    ) -> dict:
        """Build the Master Blueprint for a document. Returns
        {document_title, source_topic_count, topics}. Raises ValueError if there
        is no mapped content to consolidate (MAP produced nothing)."""
        chunks = self._collect_chunks(document_id=document_id, tenant_id=tenant_id)
        raw_topics = [
            topic
            for chunk in chunks
            for topic in ((chunk.get("topics_json") or {}).get("topics", []) or [])
        ]
        if not raw_topics:
            raise ValueError(
                "No mapped topics available to synthesize a blueprint."
            )
        merged = self._reduce(
            document_id=document_id,
            tenant_id=tenant_id,
            document_title=document_title,
            topics=raw_topics,
            document_summary=document_summary,
            profile=profile,
        )
        dropped_excerpts = keep_verified_source_excerpts(merged, chunks)
        spot_check = spot_check_verbatim_facts(merged, chunks)
        return {
            "document_title": document_title,
            "source_topic_count": len(raw_topics),
            "topics": merged,
            "verbatim_spot_check": spot_check,
            "dropped_unverified_excerpts": dropped_excerpts,
        }
