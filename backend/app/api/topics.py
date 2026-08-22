"""
Topic extraction API (blueprint quiz — Slice 6).

  POST /api/v1/documents/{document_id}/topics
    Staff-only. Reads the uploaded document and returns the list of teachable
    topics (via Gemini Flash-Lite). The teacher then selects the important ones
    and marks each High/Medium/Low on the generate screen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.lib.auth import CurrentProfile, get_current_profile
from app.services.llm import LLMError
from app.services.topics import extract_topics_for_document

router = APIRouter(prefix="/api/v1", tags=["topics"])

STAFF_ROLES = {"teacher", "institution_admin", "super_admin"}


@router.post("/documents/{document_id}/topics")
def extract_document_topics(
    document_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff can extract topics.",
        )
    try:
        topics = extract_topics_for_document(document_id, profile.tenant_id)
    except ValueError as exc:
        # bad input: document missing / no extractable text
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Topic extraction failed: {exc}",
        )
    return {"document_id": document_id, "topics": topics}
