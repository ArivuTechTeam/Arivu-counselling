"""
Topic extraction (blueprint quiz — Slice 6).

Reads a stored document's text and asks Gemini (Flash-Lite) for a clean list of
the teachable TOPICS in it. The teacher then picks the important ones and marks
each High/Medium/Low; those choices drive the blueprint in Slice 7.

Extraction is deliberately its own step (and its own cheap model call) so the
teacher can review/correct topics BEFORE any question generation happens —
"exam setter first, question writer second".
"""

from __future__ import annotations

from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text
from app.services.llm.structured import gemini_json

# responseSchema: Gemini is forced to return {"topics": ["...", ...]}.
# Gemini's REST API uses UPPERCASE OpenAPI type names (OBJECT/ARRAY/STRING).
_TOPICS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topics": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["topics"],
}

_SYSTEM = (
    "You analyse study material for an exam-prep quiz platform. Extract the list "
    "of DISTINCT teachable TOPICS/concepts a teacher would recognise (for "
    "example 'Capital Budgeting', 'Ratio Analysis', 'Depreciation Methods').\n"
    "RULES:\n"
    "- Each topic is a short noun phrase (2-6 words), NOT a sentence or question.\n"
    "- Cover the real subject concepts. IGNORE document metadata: title, author, "
    "edition, table of contents, index, preface, copyright, page numbers.\n"
    "- No duplicates and no near-duplicates.\n"
    "- Return the main teachable topics only (roughly 8-25 for a chapter).\n"
    '- Output ONLY JSON of the form {"topics": ["...", ...]}.'
)


def _window(text: str) -> str:
    """Cap how much text we send (cost control). Front matter is kept — a table
    of contents is actually helpful for naming topics."""
    return text[: get_settings().generation_max_text_chars]


def extract_topics(material: str) -> list[str]:
    """Ask Gemini for a clean, de-duplicated topic list from raw material text."""
    user = (
        "Extract the teachable topics from the material below.\n\n"
        "=== MATERIAL START ===\n" + _window(material) + "\n=== MATERIAL END ==="
    )
    data = gemini_json(_SYSTEM, user, _TOPICS_SCHEMA)

    raw = data.get("topics", [])
    seen: set[str] = set()
    topics: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = item.strip() if isinstance(item, str) else ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            topics.append(name)
    return topics[:50]


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
    return extract_topics(text)
