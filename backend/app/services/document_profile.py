"""
Document profiling — the "understand it first" step of large-document generation.

Before extracting anything, one AI call reads the document and returns what it is
fundamentally about (subject + short summary). That profile is then injected into
every MAP call and the REDUCE call so each step can judge what is core to THIS
document and what is peripheral noise — even inside a chapter, where a single
chunk in isolation often can't tell.

Best-effort: if profiling fails for any reason, we return an empty profile and the
pipeline still runs (MAP/REDUCE keep their own static "ignore non-teachable" rules).
"""

from __future__ import annotations

import logging

from app.lib.config import get_settings
from app.services.llm.structured import complete_json_large
from app.services.map_reduce_prompts import PROFILE_SYSTEM, build_profile_user_prompt

logger = logging.getLogger(__name__)


def profile_document(text: str) -> dict:
    """Return {'subject': str, 'summary': str} describing the document, or {} on
    any failure (profiling must never break a generation job)."""
    window = text[: get_settings().generation_profile_max_chars]
    if not window.strip():
        return {}
    try:
        data, _provider = complete_json_large(
            PROFILE_SYSTEM, build_profile_user_prompt(window)
        )
    except Exception as exc:  # noqa: BLE001 - best-effort; degrade gracefully
        logger.warning("Document profiling failed: %s", type(exc).__name__)
        return {}
    subject = str(data.get("subject", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not (subject or summary):
        return {}
    return {"subject": subject, "summary": summary}


def profile_to_summary(profile: dict | None) -> str:
    """Flatten a profile dict into the single guidance string passed to MAP/REDUCE."""
    profile = profile or {}
    parts = [profile.get("subject", ""), profile.get("summary", "")]
    return " ".join(p for p in parts if p).strip()
