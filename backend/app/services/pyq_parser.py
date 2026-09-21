"""Legacy experimental parser; it is intentionally not wired into production.

The supported extraction pipeline is ``quiz_extraction.py`` (DeepSeek for typed
documents and Gemini for scanned documents). Keep this module only as a reference
until a measured deterministic fast path is explicitly designed and tested.

PYQ parser — turns a TYPED MCQ document (text extracted from a PDF/DOCX via
pdfplumber) into structured questions. Deterministic, no AI.

It tolerates the real-world variations teachers produce:
  * the [PYQ]/year tag appearing ANYWHERE in a question — first, last, or on its
    own line (e.g. "[PYQ 2019]", "(PYQ 2020)", "PYQ 2018", "Previous Year 2017").
  * answers given INLINE per question ("Answer: B" / "Ans: (b)") OR collected in
    an ANSWER KEY at the end of the document ("1-A, 2-C" / "1. B" / "Q3: C").
  * options inline on one line "(A) x (B) y (C) z (D) w" or each on its own line.

Scope: TYPED text only. A scanned/image PDF yields no extractable text, so it is
out of scope here (detected upstream and rejected with a clear message).
"""

from __future__ import annotations

import re

# One inline option, up to the next "(X)" marker or end of line.
_OPT_INLINE = re.compile(r"\(([A-Da-d])\)\s*(.*?)(?=\s*\([A-Da-d]\)|$)")
# A line that is a single option: "(A) some text"
_OPT_LINE = re.compile(r"^\s*\(([A-Da-d])\)\s*(.+?)\s*$")
# Two or more option markers on the same line -> inline options.
_OPT_MULTI = re.compile(r"\([A-Da-d]\).*\([A-Da-d]\)")
# An inline answer: "Answer: B", "Ans - (b)", "Correct answer: C"
_ANS = re.compile(
    r"(?:answer|ans|correct(?:\s*answer)?)\s*[:\-]?\s*\(?([A-Da-d])\)?", re.I
)
# The PYQ tag + optional 4-digit year, wherever it sits.
_PYQ = re.compile(
    r"[\[(]?\s*(?:pyq|previous\s*year(?:\s*question)?s?)\s*[:\-]?\s*"
    r"((?:19|20)\d{2})?\s*[\])]?",
    re.I,
)
# A question start: "Q1.", "1)", "Q 2 ." followed by real text.
_QSTART = re.compile(r"^\s*Q?\s*(\d+)\s*[.)]\s+(.*\S)\s*$", re.I)
# One "number -> letter" answer-key pair: 1-A / 2. B / Q3: (c)
_KEY_PAIR = re.compile(r"(?:Q\s*)?(\d+)\s*[-.:)]\s*\(?([A-Da-d])\)?", re.I)
# A whole line that is ONLY answer-key pairs (optionally after an "Answers:" word).
_KEY_LINE = re.compile(
    r"^\s*(?:answer\s*key|answers?|key)?\s*[:\-]?\s*"
    r"(?:(?:Q\s*)?\d+\s*[-.:)]\s*\(?[A-Da-d]\)?\s*[,;]?\s*)+$",
    re.I,
)
# A standalone answer-key header line.
_KEY_HEADER = re.compile(r"^\s*(?:answer\s*key|answers?|key)\s*[:\-]?\s*$", re.I)


def parse_pyq_text(text: str) -> dict:
    """Parse typed MCQ text -> {"questions": [...], "warnings": [...]}.

    Each question: number, question_text, options{A..}, correct_answer, is_pyq, year.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    # ---- 1) Split off an answer-key section at the end (if present) ----------
    key_map: dict[int, str] = {}
    body_end = len(lines)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if _KEY_HEADER.match(s) or _KEY_LINE.match(s):
            tail = [x.strip() for x in lines[i:] if x.strip()]
            # Only treat it as THE key if the whole tail is key/header lines.
            if tail and all(
                _KEY_HEADER.match(t) or _KEY_LINE.match(t) for t in tail
            ):
                for t in tail:
                    for num, letter in _KEY_PAIR.findall(t):
                        key_map[int(num)] = letter.upper()
                body_end = i
                break
    body = lines[:body_end]

    # ---- 2) Segment the body into question blocks ---------------------------
    starts = [i for i, ln in enumerate(body) if _QSTART.match(ln)]
    questions: list[dict] = []
    warnings: list[str] = []

    for idx, s in enumerate(starts):
        e = starts[idx + 1] if idx + 1 < len(starts) else len(body)
        m = _QSTART.match(body[s])
        number = int(m.group(1))
        block = "\n".join([m.group(2)] + body[s + 1 : e])

        # PYQ tag + year anywhere in the block; then strip it out of the text.
        is_pyq = False
        year = None
        pm = _PYQ.search(block)
        if pm:
            is_pyq = True
            if pm.group(1):
                year = int(pm.group(1))
            block = _PYQ.sub(" ", block)

        # Walk the lines: build the stem, then the options.
        options: dict[str, str] = {}
        stem_parts: list[str] = []
        opt_started = False
        for ln in block.split("\n"):
            if _OPT_MULTI.search(ln):  # several options on one line
                opt_started = True
                for letter, txt in _OPT_INLINE.findall(ln):
                    options[letter.upper()] = txt.strip()
            elif _OPT_LINE.match(ln):  # one option on its own line
                lm = _OPT_LINE.match(ln)
                opt_started = True
                options[lm.group(1).upper()] = lm.group(2).strip()
            elif not opt_started and not _ANS.search(ln):
                stem_parts.append(ln.strip())
        stem = " ".join(p for p in stem_parts if p).strip()

        # Answer: inline first, else the end-of-document key.
        am = _ANS.search(block)
        answer = am.group(1).upper() if am else key_map.get(number)

        if len(options) < 2:
            warnings.append(f"Q{number}: only {len(options)} option(s) detected")
        if answer is None:
            warnings.append(f"Q{number}: no answer found (inline or in key)")

        questions.append(
            {
                "number": number,
                "question_text": stem,
                "options": options,
                "correct_answer": answer,
                "is_pyq": is_pyq,
                "year": year,
            }
        )

    return {"questions": questions, "warnings": warnings}
