"""
Structure-aware, overlapping document splitter for LARGE-document quiz
generation (chunked-generation feature, Phase 1).

Pure text logic — NO AI, NO DB, NO side effects. This module is only used by the
`else` branch of quiz generation (documents over the size threshold); small
documents never touch it and generate exactly as before.

Why this exists
---------------
Naively cutting a document every N characters can slice a concept in half — one
half in chunk A, the other in chunk B — which produces shallow or wrong questions.
This splitter avoids that with two defences:

1. Structure-aware cuts: it breaks at the strongest natural seam available
   (heading -> paragraph -> sentence), never mid-sentence.
2. Overlap: each chunk repeats a tail of the previous chunk, so a concept that
   straddles a seam is still seen whole by at least one chunk.

The character offsets (`char_start`/`char_end`) are the chunk's PRIMARY content
position in the source text (overlap is a prefix on top and is not counted), kept
for provenance/debugging by later phases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Defaults. Phase 2 makes these env-configurable; kept as module constants so the
# splitter is usable and testable in isolation now.
TARGET_CHARS = 40_000   # ~10k tokens: a big but coherent, well-read section
OVERLAP_CHARS = 5_000   # ~12%: enough to carry a straddling concept across a seam
MIN_CHARS = 8_000       # never emit a tiny orphan chunk; merge it into the previous
# Only prefer to break at a section heading once the chunk is already this full
# (a fraction of TARGET). Without this, a heading-dense document fragments into
# many tiny chunks (= many AI calls); this keeps chunks close to the target.
_HEADING_BREAK_FRACTION = 0.6


@dataclass
class GenerationChunk:
    """One unit of text handed to the model during chunked generation."""

    index: int
    content: str      # what we send the model (may start with an overlap prefix)
    char_start: int   # start offset of the chunk's PRIMARY content in the source
    char_end: int     # end offset of the chunk's PRIMARY content in the source


_PARA_SEP = re.compile(r"(\n\s*\n)")           # blank-line paragraph separators
_SENTENCE_END = re.compile(r"[.!?]\s+")        # for splitting oversize paragraphs
_HEADING = re.compile(
    r"""^\s*(
          \#{1,6}\s+                                   # markdown-style heading
        | (chapter|unit|section|part|lesson|topic)\b   # keyword heading
        | \d+(\.\d+)*[.)]?\s+\S                        # numbered: "1 ", "1.2 ", "3) "
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def _iter_paragraphs(text: str):
    """Yield (start, end, block) for each non-empty paragraph, preserving the
    original character offsets so chunks can report where they came from."""
    pos = 0
    for piece in _PARA_SEP.split(text):
        length = len(piece)
        if piece and not piece.isspace():
            yield pos, pos + length, piece
        pos += length


def _looks_like_heading(block: str) -> bool:
    """A short first line that matches a heading pattern — used only as a soft
    preference to start a new chunk on a section boundary."""
    stripped = block.strip()
    if not stripped:
        return False
    first_line = stripped.splitlines()[0]
    return len(first_line) <= 120 and bool(_HEADING.match(first_line))


def _split_oversize(start: int, block: str, target: int):
    """Split a single paragraph larger than `target` at sentence boundaries;
    hard-split only a pathological single giant sentence. Offsets are approximate
    (sentence splitting normalises whitespace) but monotonic."""
    out: list[tuple[int, int, str]] = []
    buf = ""
    buf_start = start
    pos = start
    for sentence in _SENTENCE_END.split(block):
        piece = sentence + " "
        if buf and len(buf) + len(piece) > target:
            out.append((buf_start, buf_start + len(buf), buf.strip()))
            buf = ""
            buf_start = pos
        if len(piece) > target:  # a single sentence bigger than a whole chunk
            for i in range(0, len(piece), target):
                seg = piece[i : i + target]
                out.append((pos + i, pos + i + len(seg), seg.strip()))
            pos += len(piece)
            buf_start = pos
            continue
        buf += piece
        pos += len(piece)
    if buf.strip():
        out.append((buf_start, buf_start + len(buf), buf.strip()))
    return out


def _overlap_tail(text: str, overlap: int) -> str:
    """Take the last `overlap` chars of a chunk, snapped forward to the next
    sentence start so the overlap never begins mid-sentence."""
    if overlap <= 0 or not text:
        return ""
    snippet = text[-overlap:] if len(text) > overlap else text
    match = _SENTENCE_END.search(snippet)
    if match:
        snippet = snippet[match.end() :]
    return snippet.strip()


def split_document(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
    min_chars: int = MIN_CHARS,
) -> list[GenerationChunk]:
    """Split `text` into structure-aware, overlapping chunks.

    Guarantees:
      * cuts fall on paragraph/heading/sentence seams, never mid-sentence;
      * each chunk except the first is prefixed with an overlap of the previous
        chunk's tail (snapped to a sentence boundary);
      * no tiny orphan chunk (a trailing piece < min_chars is merged back);
      * every paragraph of the source appears in at least one chunk.
    """
    if not text or not text.strip():
        return []

    # 1) Paragraphs (with offsets); explode any paragraph bigger than the target.
    blocks: list[tuple[int, int, str]] = []
    for start, end, block in _iter_paragraphs(text):
        if len(block) <= target_chars:
            blocks.append((start, end, block))
        else:
            blocks.extend(_split_oversize(start, block, target_chars))
    if not blocks:
        return []

    # 2) Greedily pack blocks into chunks; prefer to break before a heading once
    #    the current chunk is already substantial.
    raw: list[tuple[int, int, str]] = []  # (start, end, primary_content)
    cur: list[tuple[int, int, str]] = []
    cur_len = 0
    heading_floor = int(target_chars * _HEADING_BREAK_FRACTION)
    for start, end, block in blocks:
        would_exceed = cur and (cur_len + len(block) > target_chars)
        heading_break = cur and _looks_like_heading(block) and cur_len >= heading_floor
        if would_exceed or heading_break:
            raw.append((cur[0][0], cur[-1][1], "\n\n".join(b for _, _, b in cur)))
            cur = []
            cur_len = 0
        cur.append((start, end, block))
        cur_len += len(block) + 2
    if cur:
        raw.append((cur[0][0], cur[-1][1], "\n\n".join(b for _, _, b in cur)))

    # 3) Merge a tiny trailing chunk into the previous one.
    if len(raw) >= 2 and len(raw[-1][2]) < min_chars:
        s0, _e0, c0 = raw[-2]
        _s1, e1, c1 = raw[-1]
        raw[-2:] = [(s0, e1, c0 + "\n\n" + c1)]

    # 4) Add overlap prefixes.
    chunks: list[GenerationChunk] = []
    for i, (start, end, primary) in enumerate(raw):
        if i == 0:
            content = primary
        else:
            tail = _overlap_tail(raw[i - 1][2], overlap_chars)
            content = f"{tail}\n\n{primary}" if tail else primary
        chunks.append(
            GenerationChunk(index=i, content=content, char_start=start, char_end=end)
        )
    return chunks
