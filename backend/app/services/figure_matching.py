"""Deterministic figure-to-question matching (Phase 2 - no AI, no cost).

Decide whether a freshly generated question should carry one of its source
document's catalogued figures (from Phase 1), using ONLY the question's own text
and source pages plus the figure catalog. Precision-first, so a teacher confirms
in the review queue rather than cleaning up over-attachment:

  1. Explicit label - the stem names a catalog figure ("...in Figure 8.1...").
     Page-independent; highest precision.
  2. Figure mention + single page match - the stem refers to *a* figure/diagram
     ("in the given figure", "the diagram shows") AND exactly one catalogued
     figure sits on the question's source page(s).

Anything ambiguous (no reference, or several figures on the page) returns None -
attach nothing. Note the presentation validator forbids document/pdf/notes/page
references but NOT the words "figure"/"diagram", so figure-dependent stems keep
these words and are matchable here.
"""

from __future__ import annotations

import re

# A question that needs a picture says so. None of these are banned by the
# standalone-presentation rules (which target document/source references).
_FIGURE_MENTION_RE = re.compile(
    r"\b(figure|fig\.?|diagram|graph|illustrat\w*|"
    r"shown\s+(?:below|above|here|in)|given\s+(?:figure|diagram)|"
    r"adjoining\s+figure|following\s+(?:figure|diagram))\b",
    re.IGNORECASE,
)

# An explicit figure label inside the stem, e.g. "Figure 8.1", "Fig. 3.4".
_LABEL_IN_TEXT_RE = re.compile(
    r"\bfig(?:ure)?\.?\s*(\d+(?:\.\d+)*[a-z]?)\b", re.IGNORECASE
)

# The numeric portion of any catalog label ("Figure 8.1" -> "8.1", "Diagram 2" -> "2").
_LABEL_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)*[a-z]?)")


def references_a_figure(question_text: str) -> bool:
    """True when the stem refers to a figure/diagram (needs a picture)."""
    return bool(_FIGURE_MENTION_RE.search(question_text or ""))


def _label_number(label: str) -> str:
    """The comparable number of a label, tolerant of 'Figure'/'Fig.'/'Diagram' forms."""
    match = _LABEL_NUMBER_RE.search(label or "")
    return match.group(1).lower() if match else ""


def _pages(page_start, page_end) -> set[int]:
    try:
        start = int(page_start) if page_start is not None else None
        end = int(page_end) if page_end is not None else start
    except (TypeError, ValueError):
        return set()
    if start is None:
        return set()
    if end is None:
        end = start
    lo, hi = (start, end) if start <= end else (end, start)
    return set(range(lo, hi + 1))


def match_question_figure(
    catalog: list[dict],
    *,
    question_text: str,
    page_start=None,
    page_end=None,
) -> str | None:
    """Return the id of the figure this question should carry, or None.

    `catalog` rows carry at least: id, page, label.
    """
    if not catalog:
        return None
    text = question_text or ""

    # 1) Explicit label reference wins (page-independent).
    numbers_in_text = {n.lower() for n in _LABEL_IN_TEXT_RE.findall(text)}
    if numbers_in_text:
        for figure in catalog:
            if _label_number(figure.get("label", "")) in numbers_in_text:
                return figure.get("id")

    # 2) Generic figure mention + exactly one catalogued figure on the source page.
    if references_a_figure(text):
        pages = _pages(page_start, page_end)
        if pages:
            on_page = [f for f in catalog if f.get("page") in pages]
            if len(on_page) == 1:
                return on_page[0].get("id")
    return None
