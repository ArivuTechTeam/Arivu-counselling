"""Authenticated figure image proxy (student figure delivery).

Serves an extracted document figure's PNG to any authenticated user in the
figure's OWN tenant, streamed from the private `question-figures` bucket via the
service-role client.

This is how STUDENTS see question figures while taking a quiz / practice /
challenge: the frontend fetches this endpoint with its normal bearer token and
renders the bytes as a `blob:` URL. Compared with handing a student a Supabase
signed URL, this gives (a) no signed-URL expiry mid-exam, (b) per-user
authorization, and (c) no cross-origin/CSP dependency.

Additive and isolated: teacher review keeps using signed URLs (unchanged).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.storage import FIGURES_BUCKET, download_bytes
from app.lib.supabase import get_service_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/figures", tags=["figures"])


@router.get("/{figure_id}")
def get_figure_image(
    figure_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> Response:
    """Stream a figure PNG if it belongs to the caller's tenant; 404 otherwise.

    Tenant scoping (never serve another tenant's figure) is the isolation bar;
    figure images are captioned diagrams, not answer keys, and figure ids are
    unguessable UUIDs a student only ever learns for questions in their own paper.
    """
    service = get_service_client()
    row = (
        service.table("document_figures")
        .select("storage_path, tenant_id")
        .eq("id", figure_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    data = row.data if row and row.data else None
    if not data or not data.get("storage_path"):
        raise HTTPException(status_code=404, detail="Figure not found.")
    try:
        png = download_bytes(data["storage_path"], bucket=FIGURES_BUCKET)
    except Exception as exc:  # noqa: BLE001 - a storage miss is a 404 to the client
        logger.warning(
            "Figure image fetch failed for %s (%s)", figure_id, type(exc).__name__
        )
        raise HTTPException(status_code=404, detail="Figure image unavailable.") from exc
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
