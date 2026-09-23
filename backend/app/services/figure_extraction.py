"""
Figure extraction (Phase 1 of document-figure support).

Deterministic, NO-AI extraction of CAPTIONED figures from a typed PDF, so the
teacher's generated questions can later reference a real diagram from the source
document (e.g. a "find the angle" trigonometry figure) without any manual upload.

Scope (v1): only figures that carry a caption/label the text layer exposes
(e.g. "Figure 8.1 …", "Fig 3.4"). Uncaptioned / inline problem diagrams are
intentionally skipped for now (a positional-matching pass is a later phase).

Why caption-anchored: a caption is (a) a reliable signal that a real figure
exists, and (b) a natural textual description the text-only generator can use to
pick the right figure later — no vision model, so no per-question vision cost.

This module is pure/­deterministic and side-effect free: it turns PDF bytes into
`FigureCandidate`s (rendered PNG + provenance). Storage/DB wiring lives in the
job that calls `extract_document_figures`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

# Caption patterns a textbook uses. Anchored at the start of a text block so we
# don't match in-body mentions like "…as shown in Figure 3.1".
# \d+(?:\.\d+)* captures decimal figure numbers like "3.1" / "8.1" (not just "3").
_NUM = r"\d+(?:\.\d+)*[a-z]?"
_CAPTION_RE = re.compile(
    rf"^(fig(?:ure)?\.?\s*{_NUM}|diagram\s*{_NUM}|plate\s*{_NUM})\b", re.IGNORECASE
)
_LABEL_RE = re.compile(
    rf"^(fig(?:ure)?\.?\s*{_NUM}|diagram\s*{_NUM}|plate\s*{_NUM})", re.IGNORECASE
)

# Render at 2x for crisp images without ballooning size.
_RENDER_ZOOM = 2.0
# A figure region must be at least this many PDF points on each side (skip tiny
# false positives like a bare numbered list item with no drawing above it).
_MIN_REGION_PT = 40.0
# The caption sits just below its figure; allow a small gap.
_CAPTION_GAP_PT = 8.0
# A figure is at most this tall above its caption (avoid swallowing the whole page).
_MAX_FIGURE_HEIGHT_PT = 460.0
# Horizontal slack when testing whether a drawing/image shares the caption column.
_COLUMN_SLACK_PT = 45.0


@dataclass
class FigureCandidate:
    page: int  # 1-based
    bbox: dict  # {"x0","y0","x1","y1"} in PDF points
    label: str  # e.g. "Figure 8.1"
    caption: str  # full caption text
    nearby_text: str  # description for the (later) text catalog — caption for v1
    png_bytes: bytes
    width: int
    height: int


def _dedupe_caption(caption: str) -> str:
    """Collapse a repeated leading phrase in a caption.

    Some PDFs emit the caption as an overlapping/repeated text run, e.g.
    "Figure 5.2 Figure 5.2 Figure 5.2 Diagram of …". We find the smallest leading
    phrase that repeats and keep a single copy, so the catalog description the AI
    reads later is clean. Non-repeating captions are returned unchanged.
    """
    words = caption.split()
    n = len(words)
    for length in range(1, n // 2 + 1):
        block = words[:length]
        reps = 1
        while words[reps * length : (reps + 1) * length] == block:
            reps += 1
        if reps > 1:
            return " ".join(block + words[reps * length :])
    return caption


def _find_captions(page: "pymupdf.Page") -> list[tuple[str, str, "pymupdf.Rect"]]:
    """Return (caption_text, label, caption_rect) for every caption-like block."""
    found: list[tuple[str, str, pymupdf.Rect]] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        clean = _dedupe_caption(" ".join((text or "").split()))
        if not _CAPTION_RE.match(clean):
            continue
        label_match = _LABEL_RE.match(clean)
        label = label_match.group(1).strip() if label_match else clean[:40]
        found.append((clean, label, pymupdf.Rect(x0, y0, x1, y1)))
    return found


def _content_rects(page: "pymupdf.Page") -> list["pymupdf.Rect"]:
    """Bounding boxes of visual content — embedded images AND vector drawings.

    Vector coverage matters: most geometry/textbook diagrams are drawn paths,
    not raster images, so image-only extraction would miss them entirely.
    """
    rects: list[pymupdf.Rect] = []
    for image in page.get_images(full=True):
        xref = image[0]
        try:
            for rect in page.get_image_rects(xref):
                rects.append(pymupdf.Rect(rect))
        except Exception:  # noqa: BLE001 - a bad xref must not abort the page
            continue
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is not None:
            rects.append(pymupdf.Rect(rect))
    return rects


def _figure_region_for_caption(
    page: "pymupdf.Page", caption_rect: "pymupdf.Rect"
) -> "pymupdf.Rect | None":
    """Union the visual content directly ABOVE a caption, within its column.

    Textbook layout is figure-on-top, caption-below, so the figure is the union
    of image/drawing rects that (a) end at/above the caption top, (b) overlap the
    caption's horizontal span, and (c) are within a bounded height above it.
    Returns None when there's no real visual content (a false-positive caption).
    """
    region: pymupdf.Rect | None = None
    top_limit = caption_rect.y0 - _MAX_FIGURE_HEIGHT_PT
    for rect in _content_rects(page):
        if rect.width <= 2 or rect.height <= 2:
            continue
        above_caption = rect.y1 <= caption_rect.y0 + _CAPTION_GAP_PT
        within_height = rect.y0 >= top_limit
        shares_column = (
            rect.x1 >= caption_rect.x0 - _COLUMN_SLACK_PT
            and rect.x0 <= caption_rect.x1 + _COLUMN_SLACK_PT
        )
        if above_caption and within_height and shares_column:
            region = rect if region is None else (region | rect)
    if region is None:
        return None
    region = region & page.rect  # clip to the page
    if region.width < _MIN_REGION_PT or region.height < _MIN_REGION_PT:
        return None
    return region


def _render_region(
    page: "pymupdf.Page", rect: "pymupdf.Rect"
) -> tuple[bytes, int, int]:
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(_RENDER_ZOOM, _RENDER_ZOOM), clip=rect, alpha=False
    )
    return pix.tobytes("png"), pix.width, pix.height


def extract_document_figures(
    pdf_bytes: bytes, *, max_figures: int = 50
) -> list[FigureCandidate]:
    """Extract captioned figures from a typed PDF. Best-effort and bounded.

    Never raises for content problems — a page that can't be parsed is skipped so
    one bad page can't sink the whole document. Caps at `max_figures`.
    """
    candidates: list[FigureCandidate] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index in range(doc.page_count):
            page = doc[index]
            try:
                captions = _find_captions(page)
            except Exception:  # noqa: BLE001
                continue
            for caption, label, caption_rect in captions:
                try:
                    region = _figure_region_for_caption(page, caption_rect)
                    if region is None:
                        continue
                    png, width, height = _render_region(page, region)
                except Exception:  # noqa: BLE001 - skip a figure, keep the rest
                    continue
                candidates.append(
                    FigureCandidate(
                        page=index + 1,
                        bbox={
                            "x0": round(region.x0, 2),
                            "y0": round(region.y0, 2),
                            "x1": round(region.x1, 2),
                            "y1": round(region.y1, 2),
                        },
                        label=label,
                        caption=caption,
                        nearby_text=caption,
                        png_bytes=png,
                        width=width,
                        height=height,
                    )
                )
                if len(candidates) >= max_figures:
                    return candidates
    return candidates
