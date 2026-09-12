from __future__ import annotations

import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.chunking_service import ChunkingService, sha256_hex
from app.services.extraction import PageSpan
from app.services.generation_chunking import GenerationChunk

SAMPLE_PDF = (
    Path(__file__).resolve().parents[2] / "docs" / "python-basics-sample-chapters.pdf"
)

CHUNK_SETTINGS = SimpleNamespace(
    generation_chunk_chars=60_000,
    generation_chunk_overlap_chars=5_000,
    generation_chunk_min_chars=8_000,
)


def _patch_settings():
    return patch(
        "app.services.chunking_service.get_settings", return_value=CHUNK_SETTINGS
    )


# --- tiny in-memory fake of the supabase client (select/eq + insert) --------

class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.op = "select"
        self.filters = []
        self.payload = None

    def select(self, *_a):
        self.op = "select"
        return self

    def insert(self, rows):
        self.op = "insert"
        self.payload = rows
        return self

    def eq(self, k, v):
        self.filters.append((k, v))
        return self

    def execute(self):
        rows = self.db.setdefault(self.table, [])
        if self.op == "select":
            out = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
            return type("R", (), {"data": out})
        if self.op == "insert":
            created = []
            for p in self.payload:
                r = dict(p)
                r.setdefault("id", f"{self.table}-{len(rows) + len(created) + 1}")
                created.append(r)
            rows.extend(created)
            return type("R", (), {"data": created})
        return type("R", (), {"data": []})


class _Fake:
    def __init__(self):
        self.db: dict = {}

    def table(self, name):
        return _Query(self.db, name)


class HashTests(unittest.TestCase):
    def test_deterministic_and_distinct(self) -> None:
        self.assertEqual(sha256_hex("abc"), sha256_hex("abc"))
        self.assertNotEqual(sha256_hex("abc"), sha256_hex("abd"))


class StoreTests(unittest.TestCase):
    def test_idempotent_second_run_stores_nothing(self) -> None:
        fake = _Fake()
        svc = ChunkingService(service=fake)
        text = "\n\n".join(f"Paragraph {i} " * 40 for i in range(400))  # multi-chunk

        with _patch_settings():
            r1 = svc.chunk_and_store(document_id="d1", tenant_id="t1", text=text)
        self.assertGreater(r1.total, 1)
        self.assertEqual(r1.stored, r1.total)  # all new the first time

        with _patch_settings():
            r2 = svc.chunk_and_store(document_id="d1", tenant_id="t1", text=text)
        self.assertEqual(r2.stored, 0)         # nothing new on re-run
        self.assertEqual(r2.skipped, r2.total)
        # DB row count unchanged after the second run
        self.assertEqual(len(fake.db["document_chunks"]), r1.stored)

    def test_byte_identical_chunks_are_deduped(self) -> None:
        fake = _Fake()
        svc = ChunkingService(service=fake)
        same = "This is the exact same section content, repeated verbatim."
        dupes = [
            GenerationChunk(index=0, content=same, char_start=0, char_end=10),
            GenerationChunk(index=1, content=same, char_start=10, char_end=20),  # dup
        ]
        with patch.object(svc, "split", return_value=dupes):
            r = svc.chunk_and_store(document_id="d2", tenant_id="t1", text="x")
        self.assertEqual(r.total, 2)
        self.assertEqual(r.stored, 1)   # identical content stored once
        self.assertEqual(r.skipped, 1)

    def test_tenant_and_document_fields_persisted(self) -> None:
        fake = _Fake()
        svc = ChunkingService(service=fake)
        with patch.object(
            svc, "split",
            return_value=[GenerationChunk(index=0, content="hello world", char_start=0, char_end=11)],
        ):
            svc.chunk_and_store(document_id="doc-9", tenant_id="ten-9", text="x")
        row = fake.db["document_chunks"][0]
        self.assertEqual(row["document_id"], "doc-9")
        self.assertEqual(row["tenant_id"], "ten-9")
        self.assertEqual(row["content_hash"], sha256_hex("hello world"))
        self.assertEqual(row["map_status"], "queued")

    def test_approximate_page_range_is_stored_for_each_character_chunk(self) -> None:
        fake = _Fake()
        svc = ChunkingService(service=fake)
        chunks = [
            GenerationChunk(index=0, content="a", char_start=0, char_end=55),
            GenerationChunk(index=1, content="b", char_start=45, char_end=100),
        ]
        pages = (
            PageSpan(page_number=1, char_start=0, char_end=50),
            PageSpan(page_number=2, char_start=50, char_end=100),
        )
        with patch.object(svc, "split", return_value=chunks):
            svc.chunk_and_store(
                document_id="d3", tenant_id="t1", text="x" * 100,
                page_spans=pages,
            )
        rows = fake.db["document_chunks"]
        self.assertEqual((rows[0]["page_start"], rows[0]["page_end"]), (1, 2))
        self.assertEqual((rows[1]["page_start"], rows[1]["page_end"]), (1, 2))


class RealPdfSplitTests(unittest.TestCase):
    """Splits the real sample chapter (98 pages) — pure split+hash, no DB."""

    def setUp(self) -> None:
        if not SAMPLE_PDF.exists():
            self.skipTest("sample PDF not present")

    def test_real_document_chunks_are_sane(self) -> None:
        import pdfplumber  # local import so the suite doesn't hard-depend on it

        with pdfplumber.open(io.BytesIO(SAMPLE_PDF.read_bytes())) as pdf:
            text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)

        with _patch_settings():
            chunks = ChunkingService().split(text)
        self.assertGreater(len(chunks), 1, "a 98-page doc should split into several chunks")

        # every chunk within the size bound (configured target + overlap + slack)
        from app.services.generation_chunking import MIN_CHARS, OVERLAP_CHARS

        bound = 60_000 + OVERLAP_CHARS + MIN_CHARS + 500
        for c in chunks:
            self.assertLessEqual(len(c.content), bound)

        # hashes are computable and unique per distinct chunk
        hashes = [sha256_hex(c.content) for c in chunks]
        self.assertEqual(len(hashes), len(set(hashes)))

        # overlap → combined chunk text covers at least the whole document
        combined = sum(len(c.content) for c in chunks)
        self.assertGreaterEqual(combined, len(text))


if __name__ == "__main__":
    unittest.main()
