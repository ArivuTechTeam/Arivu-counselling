"""Figure-extraction quality report (dev/QA tool — Phase 1).

Runs the captioned-figure extractor over a single PDF or a folder of PDFs and:
  * prints a per-document report (pages, captions detected, figures extracted,
    and each figure's label / caption / page / size), and
  * saves the rendered PNGs so you can eyeball crop quality.

No app config, database, network, or feature flag needed — it only touches the
pure `figure_extraction` module. Safe to run anytime.

Usage (from the backend/ directory, using the venv):
  .venv/Scripts/python scripts/figure_quality_report.py <pdf-or-folder> [--out DIR] [--no-save]

Examples:
  .venv/Scripts/python scripts/figure_quality_report.py ../Testing-Quiz
  .venv/Scripts/python scripts/figure_quality_report.py ../Testing-Quiz/Maths/Maths-Trignometry.pdf --out ../.tmp/figreport
"""

from __future__ import annotations

import argparse
import os
import sys

# Make `app.*` importable when this is run from backend/.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pymupdf  # noqa: E402

from app.services.figure_extraction import (  # noqa: E402
    _find_captions,
    extract_document_figures,
)

_REPO_ROOT = os.path.dirname(_BACKEND)
_DEFAULT_OUT = os.path.join(_REPO_ROOT, ".tmp", "figreport")


def _find_pdfs(path: str) -> list[str]:
    if os.path.isfile(path) and path.lower().endswith(".pdf"):
        return [path]
    found: list[str] = []
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.lower().endswith(".pdf"):
                found.append(os.path.join(root, name))
    return sorted(found)


def _count_captions(pdf_bytes: bytes) -> int:
    total = 0
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for i in range(doc.page_count):
                total += len(_find_captions(doc[i]))
    except Exception:  # noqa: BLE001
        pass
    return total


def _report_one(path: str, out_dir: str, save: bool) -> tuple[int, int]:
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        data = fh.read()

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            pages = doc.page_count
    except Exception as exc:  # noqa: BLE001
        print(f"\n### {name}: could not open ({type(exc).__name__})")
        return 0, 0

    captions = _count_captions(data)
    figures = extract_document_figures(data, max_figures=200)

    misses = max(0, captions - len(figures))
    print(f"\n### {name}")
    print(
        f"    pages={pages}  captions_detected={captions}  "
        f"figures_extracted={len(figures)}  misses={misses}"
    )
    for fig in figures:
        kb = len(fig.png_bytes) // 1024
        cap = (fig.caption or "").replace("\n", " ")[:52]
        print(
            f"    - {fig.label:<12} p{fig.page:<3} {fig.width}x{fig.height}px "
            f"{kb:>4}KB  \"{cap}\""
        )

    if save and figures:
        doc_dir = os.path.join(out_dir, os.path.splitext(name)[0])
        os.makedirs(doc_dir, exist_ok=True)
        for k, fig in enumerate(figures, 1):
            safe_label = (fig.label or "fig").replace(" ", "_").replace("/", "-")
            fn = os.path.join(doc_dir, f"{k:02d}_{safe_label}_p{fig.page}.png")
            with open(fn, "wb") as out:
                out.write(fig.png_bytes)
        print(f"    -> {len(figures)} PNG(s) saved to {doc_dir}")

    return captions, len(figures)


def main() -> None:
    ap = argparse.ArgumentParser(description="Figure-extraction quality report")
    ap.add_argument("path", help="a PDF file or a folder of PDFs")
    ap.add_argument("--out", default=_DEFAULT_OUT, help=f"where to save PNGs (default: {_DEFAULT_OUT})")
    ap.add_argument("--no-save", action="store_true", help="report only; do not write PNGs")
    args = ap.parse_args()

    pdfs = _find_pdfs(args.path)
    if not pdfs:
        print(f"No PDFs found at {args.path}")
        return

    total_caps = total_figs = 0
    for pdf in pdfs:
        caps, figs = _report_one(pdf, args.out, save=not args.no_save)
        total_caps += caps
        total_figs += figs

    print("\n" + "=" * 60)
    print(
        f"TOTAL across {len(pdfs)} document(s): "
        f"captions_detected={total_caps}  figures_extracted={total_figs}  "
        f"misses={max(0, total_caps - total_figs)}"
    )
    if not args.no_save:
        print(f"PNGs under: {args.out}")


if __name__ == "__main__":
    main()
