"""
ChunkingService — split a large document into overlapping, hashed chunks and
persist them to `document_chunks`.

Pure code, NO AI. Used only by the large-document (> threshold) pipeline; small
documents never reach here. Responsibilities:

  * split the extracted text into structure-aware, overlapping chunks
    (reusing generation_chunking.split_document),
  * compute a SHA-256 hash of each chunk's content,
  * persist chunks, SKIPPING any that are byte-identical to one already stored
    for the same document (exact de-duplication) — this is idempotent, so
    re-running never creates duplicates.

Semantic (meaning-based) de-duplication of TOPICS happens later, in the REDUCE
step (that one needs the LLM). This service only does the cheap, exact,
code-level dedup on raw chunk text.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.generation_chunking import GenerationChunk, split_document


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(text: str) -> str:
    """Deterministic SHA-256 of the chunk content (used for exact dedup)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ChunkStoreResult:
    total: int      # chunks produced by the splitter
    stored: int     # chunks newly inserted
    skipped: int    # chunks skipped (duplicate hash or already stored)
    chunk_ids: list[str]


class ChunkingService:
    """Splits + hashes + persists document chunks (idempotent)."""

    def __init__(self, service=None) -> None:
        # `service` is injectable for tests; otherwise the service-role client.
        self._service = service

    @property
    def _client(self):
        return self._service or get_service_client()

    def split(self, text: str) -> list[GenerationChunk]:
        """Structure-aware, overlapping split using the configured sizes."""
        s = get_settings()
        return split_document(
            text,
            target_chars=s.generation_chunk_chars,
            overlap_chars=s.generation_chunk_overlap_chars,
            min_chars=s.generation_chunk_min_chars,
        )

    def chunk_and_store(
        self, *, document_id: str, tenant_id: str, text: str
    ) -> ChunkStoreResult:
        """Split the text, hash each chunk, and insert new chunks into
        `document_chunks`. Skips chunks whose content_hash (or chunk_index) is
        already stored for this document → safe to call repeatedly."""
        chunks = self.split(text)
        if not chunks:
            return ChunkStoreResult(total=0, stored=0, skipped=0, chunk_ids=[])

        client = self._client
        existing = (
            client.table("document_chunks")
            .select("chunk_index, content_hash")
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
        seen_index = {r["chunk_index"] for r in existing}
        seen_hash = {r["content_hash"] for r in existing}

        rows: list[dict] = []
        for c in chunks:
            content_hash = sha256_hex(c.content)
            # Skip exact duplicates (same content already stored, or repeated in
            # this batch) and anything already persisted for this chunk_index.
            if content_hash in seen_hash or c.index in seen_index:
                continue
            seen_hash.add(content_hash)
            seen_index.add(c.index)
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "chunk_index": c.index,
                    "content": c.content,
                    "content_hash": content_hash,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "map_status": "queued",
                    "attempts": 0,
                    "updated_at": _now(),
                }
            )

        chunk_ids: list[str] = []
        if rows:
            resp = client.table("document_chunks").insert(rows).execute()
            chunk_ids = [r.get("id") for r in (resp.data or []) if r.get("id")]

        return ChunkStoreResult(
            total=len(chunks),
            stored=len(rows),
            skipped=len(chunks) - len(rows),
            chunk_ids=chunk_ids,
        )
