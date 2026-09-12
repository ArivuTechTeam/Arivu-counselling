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

from pydantic import ValidationError

from app.lib.supabase import get_service_client
from app.services.llm.base import LLMError
from app.services.llm.structured import complete_json_large
from app.services.map_reduce_prompts import REDUCE_SYSTEM, build_reduce_user_prompt
from app.services.topic_extraction_pipeline import validate_map_output


class MasterBlueprintSynthesizer:
    def __init__(self, service=None) -> None:
        self._service = service  # injectable for tests

    def _collect_topics(self, *, document_id: str, tenant_id: str) -> list[dict]:
        """Flatten the topics from every SUCCEEDED chunk, in reading order."""
        client = self._service or get_service_client()
        rows = (
            client.table("document_chunks")
            .select("chunk_index, map_status, topics_json")
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .order("chunk_index")
            .execute()
            .data
            or []
        )
        topics: list[dict] = []
        for row in sorted(rows, key=lambda r: r["chunk_index"]):
            if row.get("map_status") != "succeeded":
                continue
            topics.extend((row.get("topics_json") or {}).get("topics", []) or [])
        return topics

    def _reduce(
        self, *, document_title: str, topics: list[dict], document_summary: str = ""
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
    ) -> dict:
        """Build the Master Blueprint for a document. Returns
        {document_title, source_topic_count, topics}. Raises ValueError if there
        is no mapped content to consolidate (MAP produced nothing)."""
        raw_topics = self._collect_topics(
            document_id=document_id, tenant_id=tenant_id
        )
        if not raw_topics:
            raise ValueError(
                "No mapped topics available to synthesize a blueprint."
            )
        merged = self._reduce(
            document_title=document_title,
            topics=raw_topics,
            document_summary=document_summary,
        )
        return {
            "document_title": document_title,
            "source_topic_count": len(raw_topics),
            "topics": merged,
        }
