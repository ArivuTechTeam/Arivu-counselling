"""Store & serve extracted document figures (Phase 1 orchestration).

Pairs the pure `figure_extraction` module with storage + DB:
  * `store_document_figures` — extract captioned figures from a document's PDF,
    upload each PNG to the private `question-figures` bucket, and record catalog
    rows. Idempotent per document (a re-run refreshes figures in place so stable
    question links survive).
    Best-effort: it never raises to its caller, so figure work can never break
    the analysis pipeline it runs inside.
  * `list_document_figures` — the catalog for a document, each row carrying a
    short-lived signed URL (for the Phase-1 inspection endpoint / later review).
"""

from __future__ import annotations

import logging
import uuid

from app.lib.config import get_settings
from app.lib.storage import (
    FIGURES_BUCKET,
    delete_bytes,
    download_bytes,
    replace_bytes,
    signed_url,
    upload_bytes,
)
from app.services.figure_extraction import extract_document_figures
from app.services.figure_matching import match_question_figure
from app.services.tenant_features import tenant_feature_enabled

logger = logging.getLogger(__name__)

_SIGNED_URL_TTL_SECONDS = 600  # 10 minutes


def extract_and_store_for_document(
    service, *, tenant_id: str, document_id: str
) -> int:
    """Flag-gated, best-effort figure extraction for one document (PDF only).

    Safe to call from the analysis job: returns 0 (a no-op) when the feature flag
    is off or the document isn't a PDF, and never raises.
    """
    settings = get_settings()
    if not settings.figure_attach_enabled or not tenant_feature_enabled(
        service, tenant_id, "figure_attach"
    ):
        return 0
    try:
        doc = (
            service.table("documents")
            .select("storage_path, file_type")
            .eq("id", document_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )
        row = doc.data if doc and doc.data else None
        if not row or (row.get("file_type") or "").lower() != "pdf":
            return 0
        pdf_bytes = download_bytes(row["storage_path"])  # source-documents bucket
    except Exception:  # noqa: BLE001 - a fetch problem must not break analysis
        logger.warning("Figure prep failed")
        return 0
    return store_document_figures(
        service,
        tenant_id=tenant_id,
        document_id=document_id,
        pdf_bytes=pdf_bytes,
        max_figures=settings.figure_max_per_document,
    )


def _figure_key(page, label) -> tuple[int | None, str]:
    """Stable identity for the captioned figures supported by the v1 extractor."""
    return page, " ".join(str(label or "").casefold().split())


def _existing_figures(service, tenant_id: str, document_id: str) -> list[dict]:
    return (
        service.table("document_figures")
        .select("id, page, label, storage_path")
        .eq("tenant_id", tenant_id)
        .eq("document_id", document_id)
        .execute()
        .data
        or []
    )


def store_document_figures(
    service,
    *,
    tenant_id: str,
    document_id: str,
    pdf_bytes: bytes,
    max_figures: int = 50,
) -> int:
    """Extract + persist captioned figures for a document. Returns the count stored.

    Best-effort: any failure is logged and returns the count stored so far; it
    never raises. Idempotent — refreshes matching figures in place and removes
    stale rows only after a complete successful refresh.
    """
    try:
        candidates = extract_document_figures(pdf_bytes, max_figures=max_figures)
    except Exception:  # noqa: BLE001 - extraction failure must not break analysis
        logger.warning("Figure extraction failed")
        return 0

    try:
        existing = _existing_figures(service, tenant_id, document_id)
    except Exception:  # noqa: BLE001 - a catalog read must not break analysis
        logger.warning("Existing figure lookup failed")
        return 0

    # An empty extraction can mean that the source contains no supported
    # captioned figures, but it can also be a parser/rendering degradation. Keep
    # existing linked figures in that ambiguous case rather than silently
    # stripping them from already-published questions.
    if not candidates:
        return 0

    by_key = {
        _figure_key(row.get("page"), row.get("label")): row
        for row in existing
        if row.get("id") and row.get("storage_path")
    }
    retained_ids: set[str] = set()
    refresh_complete = True

    stored = 0
    for candidate in candidates:
        old = by_key.get(_figure_key(candidate.page, candidate.label))
        figure_id = old["id"] if old else str(uuid.uuid4())
        path = old["storage_path"] if old else f"{tenant_id}/{document_id}/{figure_id}.png"
        try:
            fields = {
                "page": candidate.page,
                "bbox": candidate.bbox,
                "label": candidate.label,
                "caption": candidate.caption,
                "nearby_text": candidate.nearby_text,
                "storage_path": path,
                "width": candidate.width,
                "height": candidate.height,
            }
            if old:
                replace_bytes(path, candidate.png_bytes, "image/png", bucket=FIGURES_BUCKET)
                service.table("document_figures").update(fields) \
                    .eq("id", figure_id).eq("tenant_id", tenant_id).execute()
            else:
                upload_bytes(path, candidate.png_bytes, "image/png", bucket=FIGURES_BUCKET)
                service.table("document_figures").insert({
                    "id": figure_id,
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    **fields,
                }).execute()
            retained_ids.add(figure_id)
            stored += 1
        except Exception:  # noqa: BLE001 - skip a bad figure, keep the rest
            refresh_complete = False
            if not old:
                try:
                    delete_bytes(path, bucket=FIGURES_BUCKET)
                except Exception:  # noqa: BLE001 - best-effort orphan cleanup
                    pass
            logger.warning("Storing figure failed")
            continue

    # Delete figures no longer present only after every replacement/insert
    # succeeded. This preserves existing question links during partial refreshes.
    stale = [row for row in existing if row.get("id") not in retained_ids]
    if refresh_complete and stale:
        stale_paths = [row["storage_path"] for row in stale if row.get("storage_path")]
        try:
            if stale_paths:
                delete_bytes(stale_paths, bucket=FIGURES_BUCKET)
            service.table("document_figures").delete() \
                .eq("tenant_id", tenant_id).eq("document_id", document_id) \
                .in_("id", [row["id"] for row in stale]).execute()
        except Exception:  # noqa: BLE001 - stale cleanup must not break analysis
            logger.warning("Stale figure cleanup failed")
    return stored


def _figure_catalog_for_matching(
    service, tenant_id: str, document_id: str
) -> list[dict]:
    """Minimal catalog (id, page, label) used by deterministic question matching."""
    return (
        service.table("document_figures")
        .select("id, page, label")
        .eq("tenant_id", tenant_id)
        .eq("document_id", document_id)
        .execute()
        .data
        or []
    )


def attach_figures_to_questions(
    service, *, tenant_id: str, document_id: str, questions: list[dict]
) -> int:
    """Best-effort: set `questions.figure_id` for questions that reference a
    catalogued figure of their source document.

    Runs AFTER the quiz is persisted, keyed on each question's own id — so it is
    fully decoupled from the (transactional) generation/commit path and can never
    break generation. `questions` are the persisted result rows, each carrying at
    least: id, question_text, source_page_start, source_page_end.

    Flag-gated by FIGURE_ATTACH_ENABLED; a no-op (returns 0) when the flag is off,
    the document has no figures, or `document_id` is missing. Never raises.
    Returns the number of questions linked to a figure.
    """
    if (
        not document_id
        or not get_settings().figure_attach_enabled
        or not tenant_feature_enabled(service, tenant_id, "figure_attach")
    ):
        return 0
    try:
        catalog = _figure_catalog_for_matching(service, tenant_id, document_id)
    except Exception:  # noqa: BLE001 - a catalog read problem must not affect the quiz
        logger.warning("Figure catalog read failed")
        return 0
    if not catalog:
        return 0

    linked = 0
    for question in questions or []:
        question_id = question.get("id")
        if not question_id:
            continue
        figure_id = match_question_figure(
            catalog,
            question_text=question.get("question_text", ""),
            page_start=question.get("source_page_start"),
            page_end=question.get("source_page_end"),
        )
        if not figure_id:
            continue
        try:
            service.table("questions").update({"figure_id": figure_id}).eq(
                "id", question_id
            ).eq("tenant_id", tenant_id).execute()
            linked += 1
        except Exception:  # noqa: BLE001 - one failed link must not stop the rest
            logger.warning("Linking figure to question failed")
            continue
    return linked


def purge_figures_for_documents(
    service, *, tenant_id: str, document_ids: list[str], strict: bool = False
) -> int:
    """Delete figure storage objects + catalog rows for the given documents.

    Used when a user's documents are hard-deleted or their account is erased, so
    the rendered figure PNGs neither orphan in the bucket (cost) nor survive the
    erasure of the source personal data (privacy). Routine cleanup is
    best-effort. Account erasure sets strict=True so a failed lookup, object
    removal, or row removal stops deletion instead of reporting success.
    """
    ids = [d for d in dict.fromkeys(document_ids) if d]
    if not ids:
        return 0
    try:
        rows = (
            service.table("document_figures")
            .select("storage_path")
            .eq("tenant_id", tenant_id)
            .in_("document_id", ids)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 - routine cleanup remains best-effort
        logger.warning("Figure purge lookup failed for %d document(s)", len(ids))
        if strict:
            raise
        return 0
    paths = [r["storage_path"] for r in rows if r.get("storage_path")]
    if paths:
        try:
            delete_bytes(paths, bucket=FIGURES_BUCKET)
        except Exception:  # noqa: BLE001 - routine cleanup remains best-effort
            logger.warning("Figure object purge failed for %d object(s)", len(paths))
            if strict:
                raise
    try:
        service.table("document_figures").delete().eq("tenant_id", tenant_id).in_(
            "document_id", ids
        ).execute()
    except Exception:  # noqa: BLE001 - rows may also cascade-delete with the document
        logger.warning("Figure row purge failed")
        if strict:
            raise
    return len(paths)


def figures_for_questions(
    service, *, tenant_id: str, figure_ids: list[str]
) -> dict[str, dict]:
    """Map figure_id -> {id, page, label, caption, url} for review display.

    Batches one lookup for many questions; each figure carries a short-lived
    signed image URL. Tenant-scoped. Never raises for a single broken object.
    """
    ids = [fid for fid in dict.fromkeys(figure_ids) if fid]
    if not ids:
        return {}
    rows = (
        service.table("document_figures")
        .select("id, page, label, caption, storage_path")
        .eq("tenant_id", tenant_id)
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    result: dict[str, dict] = {}
    for row in rows:
        url = None
        try:
            url = signed_url(
                row["storage_path"], _SIGNED_URL_TTL_SECONDS, bucket=FIGURES_BUCKET
            )
        except Exception:  # noqa: BLE001 - a broken object shouldn't drop the rest
            logger.warning("Signed URL failed for figure")
        result[row["id"]] = {
            "id": row["id"],
            "page": row.get("page"),
            "label": row.get("label"),
            "caption": row.get("caption"),
            "url": url,
        }
    return result


def list_document_figures(service, *, tenant_id: str, document_id: str) -> list[dict]:
    """Return a document's figure catalog with short-lived signed image URLs."""
    rows = (
        service.table("document_figures")
        .select("id, page, label, caption, width, height, storage_path")
        .eq("tenant_id", tenant_id)
        .eq("document_id", document_id)
        .order("page")
        .execute()
        .data
        or []
    )
    figures: list[dict] = []
    for row in rows:
        url = None
        try:
            url = signed_url(
                row["storage_path"], _SIGNED_URL_TTL_SECONDS, bucket=FIGURES_BUCKET
            )
        except Exception:  # noqa: BLE001 - a broken object shouldn't drop the whole list
            logger.warning("Signed URL failed for figure")
        figures.append(
            {
                "id": row["id"],
                "page": row.get("page"),
                "label": row.get("label"),
                "caption": row.get("caption"),
                "width": row.get("width"),
                "height": row.get("height"),
                "url": url,
            }
        )
    return figures
