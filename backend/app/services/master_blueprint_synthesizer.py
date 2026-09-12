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
from app.services.map_reduce_prompts import REDUCE_SYSTEM, build_reduce_user_prompt
from app.services.topic_extraction_pipeline import validate_map_output
from app.services.rate_limit import TOPIC_EXTRACTION, enforce_ai_rate_limit

logger = logging.getLogger(__name__)


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
        document_title: str,
        topics: list[dict],
        document_summary: str = "",
        profile: CurrentProfile | None = None,
    ) -> list[dict]:
        """One LLM call to merge/de-duplicate, retrying once on a transient error."""
        user = build_reduce_user_prompt(
            document_title=document_title,
            topics_json=json.dumps(topics, ensure_ascii=False),
            document_summary=document_summary,
        )
        last_error: Exception | None = None
        for _ in range(2):
            try:
                if profile is not None:
                    enforce_ai_rate_limit(
                        profile=profile,
                        endpoint=TOPIC_EXTRACTION,
                        hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
                        action_label="large-document analysis",
                    )
                data, _provider = complete_json_large(REDUCE_SYSTEM, user)
                return validate_map_output(data)
            except (LLMError, ValidationError) as exc:
                last_error = exc
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
            document_title=document_title,
            topics=raw_topics,
            document_summary=document_summary,
            profile=profile,
        )
        spot_check = spot_check_verbatim_facts(merged, chunks)
        return {
            "document_title": document_title,
            "source_topic_count": len(raw_topics),
            "topics": merged,
            "verbatim_spot_check": spot_check,
        }
