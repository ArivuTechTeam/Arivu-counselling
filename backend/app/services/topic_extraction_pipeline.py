"""
TopicExtractionPipeline — the MAP phase of large-document quiz generation.

For each stored `document_chunks` row, make ONE LLM call to extract rich,
verbatim study content (topics, definitions, facts, formulas, worked examples),
then checkpoint the result (`topics_json` + `map_status`) on that row.

Resumable: only chunks whose map_status is queued/failed are (re)processed;
succeeded chunks keep their stored result and are never re-mapped. Chunks run in
a bounded parallel pool; each worker uses its own service client (thread-safe),
retries once on a transient model error, and a single failed chunk never sinks
the others.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pydantic import ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.llm.base import LLMError
from app.services.llm.structured import complete_json_large
from app.services.map_reduce_prompts import MAP_SYSTEM, build_map_user_prompt
from app.services.rate_limit import TOPIC_EXTRACTION, enforce_ai_rate_limit
from app.services.source_material import (
    evidence_occurs_in_material,
    is_meaningful_evidence,
    normalise_evidence,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_map_output(data: object) -> list[dict]:
    """Normalise the model's JSON into a clean list of topic objects. Tolerant:
    drops junk, coerces missing arrays to [], keeps only topics with a name."""
    topics = data.get("topics") if isinstance(data, dict) else None
    out: list[dict] = []
    for t in topics or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("topic_name", "")).strip()
        if not name:
            continue
        out.append(
            {
                "topic_name": name,
                "subtopics": [
                    s.strip()
                    for s in (t.get("subtopics") or [])
                    if isinstance(s, str) and s.strip()
                ],
                "key_definitions": [
                    d
                    for d in (t.get("key_definitions") or [])
                    if isinstance(d, dict) and str(d.get("term", "")).strip()
                ],
                "key_facts_and_figures": [
                    f.strip()
                    for f in (t.get("key_facts_and_figures") or [])
                    if isinstance(f, str) and f.strip()
                ],
                "formulas": [
                    f
                    for f in (t.get("formulas") or [])
                    if isinstance(f, dict) and str(f.get("formula", "")).strip()
                ],
                "worked_examples": [
                    w
                    for w in (t.get("worked_examples") or [])
                    if isinstance(w, dict)
                    and (
                        str(w.get("full_example_text", "")).strip()
                        or str(w.get("description", "")).strip()
                    )
                ],
                "source_excerpts": [
                    {
                        "text": str(excerpt.get("text", "")).strip(),
                        "page_start": (
                            int(excerpt["page_start"])
                            if str(excerpt.get("page_start", "")).isdigit()
                            else None
                        ),
                        "page_end": (
                            int(excerpt["page_end"])
                            if str(excerpt.get("page_end", "")).isdigit()
                            else None
                        ),
                    }
                    for excerpt in (t.get("source_excerpts") or [])
                    if isinstance(excerpt, dict)
                    and is_meaningful_evidence(str(excerpt.get("text", "")).strip())
                ],
                "source_page_ranges": [
                    {"start": int(r["start"]), "end": int(r["end"])}
                    for r in (t.get("source_page_ranges") or [])
                    if isinstance(r, dict)
                    and str(r.get("start", "")).isdigit()
                    and str(r.get("end", "")).isdigit()
                    and int(r["start"]) > 0
                    and int(r["end"]) >= int(r["start"])
                ],
            }
        )
    return out


def align_topic_name_to_source(topic: dict, content: str) -> None:
    """Prefer an explicit source term when the model invents a broader label."""
    name = str(topic.get("topic_name") or "").strip()
    source = normalise_evidence(content)
    if name and normalise_evidence(name) in source:
        return
    candidates = [
        str(item.get("name") or "").strip()
        for item in (topic.get("formulas") or [])
        if isinstance(item, dict)
    ] + [
        str(item.get("term") or "").strip()
        for item in (topic.get("key_definitions") or [])
        if isinstance(item, dict)
    ]
    replacement = next(
        (
            candidate
            for candidate in candidates
            if candidate and normalise_evidence(candidate) in source
        ),
        None,
    )
    if replacement:
        topic["topic_name"] = replacement


class TopicExtractionPipeline:
    def __init__(self, service=None) -> None:
        self._service = service  # injectable for tests

    def _extract(
        self,
        *,
        document_title: str,
        chunk_number: int,
        total_chunks: int,
        content: str,
        document_summary: str = "",
        page_start: int | None = None,
        page_end: int | None = None,
        profile: CurrentProfile | None = None,
    ) -> list[dict]:
        """One chunk → topics, retrying once on a transient model error."""
        user = build_map_user_prompt(
            document_title=document_title,
            chunk_number=chunk_number + 1,  # 1-based for the prompt
            total_chunks=total_chunks,
            content=content,
            document_summary=document_summary,
            page_start=page_start,
            page_end=page_end,
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
                data, _provider = complete_json_large(MAP_SYSTEM, user)
                topics = validate_map_output(data)
                for topic in topics:
                    align_topic_name_to_source(topic, content)
                    topic["formulas"] = [
                        formula
                        for formula in (topic.get("formulas") or [])
                        if evidence_occurs_in_material(
                            str(formula.get("formula") or ""), content
                        )
                    ]
                    topic["source_excerpts"] = [
                        excerpt
                        for excerpt in (topic.get("source_excerpts") or [])
                        if evidence_occurs_in_material(excerpt["text"], content)
                    ]
                if page_start is not None and page_end is not None:
                    for topic in topics:
                        topic["source_page_ranges"] = [
                            {"start": page_start, "end": page_end}
                        ]
                        for excerpt in topic.get("source_excerpts") or []:
                            excerpt["page_start"] = page_start
                            excerpt["page_end"] = page_end
                return topics
            except (LLMError, ValidationError) as exc:
                last_error = exc
        raise last_error or LLMError("Topic extraction failed for a chunk.")

    def _map_one(
        self,
        *,
        document_title: str,
        total_chunks: int,
        chunk: dict,
        document_summary: str = "",
        profile: CurrentProfile | None = None,
    ) -> None:
        """Claim a chunk, extract its topics, and checkpoint the result. Uses its
        OWN client so parallel workers don't share one connection."""
        client = self._service or get_service_client()
        claimed = (
            client.table("document_chunks")
            .update(
                {
                    "map_status": "running",
                    "attempts": (chunk.get("attempts") or 0) + 1,
                    "updated_at": _now(),
                }
            )
            .eq("id", chunk["id"])
            .in_("map_status", ["queued", "failed"])
            .execute()
        )
        if not claimed.data:  # already claimed/finished by someone else
            return
        try:
            topics = self._extract(
                document_title=document_title,
                chunk_number=chunk["chunk_index"],
                total_chunks=total_chunks,
                content=chunk["content"],
                document_summary=document_summary,
                page_start=chunk.get("page_start"),
                page_end=chunk.get("page_end"),
                profile=profile,
            )
            client.table("document_chunks").update(
                {
                    "map_status": "succeeded",
                    "topics_json": {"topics": topics},
                    "error_message": None,
                    "updated_at": _now(),
                }
            ).eq("id", chunk["id"]).execute()
        except Exception as exc:  # noqa: BLE001 - record; retry handled by resume
            client.table("document_chunks").update(
                {"map_status": "failed", "error_message": str(exc)[:500], "updated_at": _now()}
            ).eq("id", chunk["id"]).execute()

    def run(
        self,
        *,
        document_id: str,
        tenant_id: str,
        document_title: str = "",
        document_summary: str = "",
        profile: CurrentProfile | None = None,
    ) -> dict:
        """Map every not-yet-succeeded chunk of a document (parallel, resumable).
        Returns {total, succeeded, failed}."""
        client = self._service or get_service_client()
        chunks = (
            client.table("document_chunks")
            .select(
                "id, chunk_index, content, map_status, attempts, page_start, page_end"
            )
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .order("chunk_index")
            .execute()
            .data
            or []
        )
        total = len(chunks)
        pending = [c for c in chunks if c["map_status"] in ("queued", "failed")]

        if pending:
            workers = max(
                1, min(get_settings().generation_chunk_concurrency, len(pending))
            )
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(
                    pool.map(
                        lambda c: self._map_one(
                            document_title=document_title,
                            total_chunks=total,
                            chunk=c,
                            document_summary=document_summary,
                            profile=profile,
                        ),
                        pending,
                    )
                )

        rows = (
            client.table("document_chunks")
            .select("map_status")
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
        succeeded = sum(1 for r in rows if r["map_status"] == "succeeded")
        failed = sum(1 for r in rows if r["map_status"] == "failed")
        return {"total": total, "succeeded": succeeded, "failed": failed}
