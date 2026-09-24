"""Public, read-only institution branding used by tenant login pages."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.lib.storage import signed_url
from app.lib.supabase import get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/public/institutions", tags=["public branding"])

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InstitutionBranding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    name: str
    subdomain: str
    logo_url: str | None
    primary_color: str


@router.get("/{subdomain}/branding", response_model=InstitutionBranding)
def institution_branding(subdomain: str) -> dict:
    """Return only the safe branding fields needed before authentication."""
    slug = subdomain.strip().lower()
    if not _SLUG.fullmatch(slug):
        raise HTTPException(status_code=404, detail="Institution login link not found.")

    result = (
        get_service_client()
        .table("tenants")
        .select("id, name, subdomain, logo_url, primary_color")
        .eq("subdomain", slug)
        .eq("is_active", True)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="Institution login link not found.")

    stored_logo = result.data.get("logo_url")
    browser_logo: str | None = None
    if isinstance(stored_logo, str) and stored_logo:
        try:
            browser_logo = signed_url(stored_logo, expires_in=3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Institution logo URL could not be created (%s)",
                type(exc).__name__,
            )

    return {
        "tenant_id": str(result.data["id"]),
        "name": result.data["name"],
        "subdomain": result.data["subdomain"],
        "logo_url": browser_logo,
        "primary_color": result.data.get("primary_color") or "#2E8857",
    }
