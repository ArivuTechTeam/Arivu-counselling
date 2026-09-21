"""
Topic extraction API (blueprint quiz — Slice 6).

  POST /api/v1/documents/{document_id}/topics
    Staff-only. Reads the uploaded document and returns the list of teachable
    topics through the configured stage-aware text provider (DeepSeek by
    default, with Gemini fallback). The teacher then selects the important ones
    and marks each High/Medium/Low on the generate screen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.llm import LLMError
from app.services.rate_limit import TOPIC_EXTRACTION, enforce_ai_rate_limit
from app.services.topic_capacity import selectable_topic_choices
from app.services.topics import extract_topic_details_for_document

router = APIRouter(prefix="/api/v1", tags=["topics"])


@router.post("/documents/{document_id}/topics")
def extract_document_topics(
    document_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can extract topics.",
        )
    service = get_service_client()
    document = (
        service.table("documents")
        .select("id")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if document is None or not document.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    enforce_ai_rate_limit(
        profile=profile,
        endpoint=TOPIC_EXTRACTION,
        hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
        action_label="topic extraction",
    )
    try:
        topic_details = extract_topic_details_for_document(
            document_id, profile.tenant_id
        )
    except ValueError as exc:
        raise public_error(
            status.HTTP_400_BAD_REQUEST,
            "This document could not be used for topic extraction. Check the file and try again.",
            operation="prepare document for topic extraction",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't extract topics right now. Please try again.",
            operation="extract document topics with AI",
            exception=exc,
        ) from exc
    topic_choices = selectable_topic_choices(topic_details)
    return {
        "document_id": document_id,
        "topics": [topic["name"] for topic in topic_choices],
        "topic_groups": topic_choices,
        "topic_question_limits": {
            topic["name"]: topic["suggested_question_limit"]
            for topic in topic_choices
        },
    }
