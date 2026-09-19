"""
Topic extraction (blueprint quiz — Slice 6).

Reads a stored document and uses the shared grounded extraction pipeline for a
clean list of teachable topics plus verified supporting material. The teacher
then chooses topics and exact question-format counts for the blueprint.

Extraction is deliberately its own step (and its own model call) so the
teacher can review/correct topics BEFORE any question generation happens —
"exam setter first, question writer second".
"""

from __future__ import annotations

from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text
from app.services.topic_extraction_pipeline import TopicExtractionPipeline
from app.services.ai_call_logging import ai_call_context

def _window(text: str) -> str:
    """Cap the direct-document extraction input using the configured ceiling."""
    return text[: get_settings().generation_max_text_chars]


def extract_topic_details(
    material: str,
    document_summary: str = "",
    *,
    tenant_id: str | None = None,
    document_id: str | None = None,
) -> list[dict]:
    """Use the same grounded rich extraction contract for every document size."""
    with ai_call_context(
        "topic_extraction", tenant_id=tenant_id, document_id=document_id
    ):
        topics = TopicExtractionPipeline()._extract(
            document_title="Uploaded study material",
            chunk_number=0,
            total_chunks=1,
            content=_window(material),
            document_summary=document_summary,
        )
    return topics[:50]


def extract_topics(
    material: str,
    document_summary: str = "",
    *,
    tenant_id: str | None = None,
    document_id: str | None = None,
) -> list[str]:
    """Backward-compatible topic-name view of grounded rich extraction."""
    return [
        str(topic.get("topic_name") or "").strip()
        for topic in extract_topic_details(
            material, document_summary, tenant_id=tenant_id, document_id=document_id
        )
        if str(topic.get("topic_name") or "").strip()
    ]


def extract_topics_for_document(document_id: str, tenant_id: str) -> list[str]:
    """Fetch a stored document (tenant-scoped), extract its text, return topics."""
    service = get_service_client()
    doc = (
        service.table("documents")
        .select("*")
        .eq("id", document_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")

    content = download_bytes(doc.data["storage_path"])
    text = extract_text(content, doc.data["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    return extract_topics(text, tenant_id=tenant_id, document_id=document_id)


def extract_topic_details_for_document(document_id: str, tenant_id: str) -> list[dict]:
    """Fetch a stored document and return verified rich topic details."""
    service = get_service_client()
    doc = (
        service.table("documents")
        .select("storage_path,file_type")
        .eq("id", document_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    text = extract_text(download_bytes(doc.data["storage_path"]), doc.data["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    return extract_topic_details(text, tenant_id=tenant_id, document_id=document_id)
