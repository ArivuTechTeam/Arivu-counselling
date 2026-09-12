from __future__ import annotations

import unittest

from app.services.generation_chunking import (
    MIN_CHARS,
    OVERLAP_CHARS,
    TARGET_CHARS,
    split_document,
)


def _para(marker: str, filler_words: int = 60) -> str:
    """A paragraph carrying a unique marker, ending in a full stop so we can
    assert clean sentence-boundary cuts."""
    body = " ".join(f"word{marker}{i}" for i in range(filler_words))
    return f"Paragraph {marker}: {body}."


class GenerationChunkingTests(unittest.TestCase):
    def test_empty_returns_nothing(self) -> None:
        self.assertEqual(split_document(""), [])
        self.assertEqual(split_document("   \n\n  "), [])

    def test_small_document_is_one_chunk_with_no_overlap(self) -> None:
        text = "\n\n".join(_para(str(i)) for i in range(5))  # well under target
        chunks = split_document(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].index, 0)
        # Single chunk == the original content, no duplication.
        self.assertEqual(chunks[0].content.strip(), text.strip())

    def test_large_document_splits_into_multiple_bounded_chunks(self) -> None:
        # ~200 paragraphs of ~ a few hundred chars → comfortably over target.
        text = "\n\n".join(_para(f"{i:04d}") for i in range(400))
        self.assertGreater(len(text), TARGET_CHARS)
        chunks = split_document(text)

        self.assertGreater(len(chunks), 1)
        # Each chunk's content stays within target + overlap (+ small slack for
        # the tiny-trailing-merge case and join characters).
        upper_bound = TARGET_CHARS + OVERLAP_CHARS + MIN_CHARS + 500
        for c in chunks:
            self.assertLessEqual(len(c.content), upper_bound)
        # Indexes are sequential.
        self.assertEqual([c.index for c in chunks], list(range(len(chunks))))

    def test_every_paragraph_is_covered(self) -> None:
        markers = [f"{i:04d}" for i in range(400)]
        text = "\n\n".join(_para(m) for m in markers)
        chunks = split_document(text)
        joined = "\n\n".join(c.content for c in chunks)
        for m in markers:
            self.assertIn(f"Paragraph {m}:", joined)  # nothing dropped

    def test_adjacent_chunks_overlap(self) -> None:
        text = "\n\n".join(_para(f"{i:04d}") for i in range(400))
        chunks = split_document(text)
        self.assertGreater(len(chunks), 1)
        # The start of each later chunk should be text that also appeared in the
        # previous chunk (the overlap prefix).
        for i in range(1, len(chunks)):
            head = chunks[i].content[:200]
            prev = chunks[i - 1].content
            # take a distinctive token from the head and confirm it's in prev
            token = next((t for t in head.split() if t.startswith("word")), None)
            self.assertIsNotNone(token, "expected a content token at chunk head")
            self.assertIn(token, prev, f"chunk {i} start not overlapping chunk {i-1}")

    def test_no_midsentence_cut_on_primary_content(self) -> None:
        # Primary content of every chunk should end at a sentence boundary
        # (our paragraphs end with '.').
        text = "\n\n".join(_para(f"{i:04d}") for i in range(400))
        chunks = split_document(text)
        for c in chunks:
            self.assertTrue(
                c.content.rstrip().endswith((".", "!", "?")),
                "chunk did not end on a sentence boundary",
            )

    def test_oversize_single_paragraph_is_sentence_split(self) -> None:
        # One giant paragraph (no blank lines) far larger than target.
        big = " ".join(f"This is sentence number {i}." for i in range(6000))
        self.assertGreater(len(big), TARGET_CHARS)
        chunks = split_document(big)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c.content), TARGET_CHARS + OVERLAP_CHARS + 500)


if __name__ == "__main__":
    unittest.main()
