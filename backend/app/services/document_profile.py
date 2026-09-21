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
    """Return a subject-neutral content profile, or ``{}`` on any failure."""
    if not text.strip():
        return {}
    window = text[: get_settings().generation_profile_max_chars]
    try:
        data, _provider = complete_json_large(
            PROFILE_SYSTEM,
            build_profile_user_prompt(window),
            preferred_provider=getattr(
                get_settings(), "topic_analysis_provider", "deepseek"
            ),
        )
    except Exception as exc:  # noqa: BLE001 - best-effort; degrade gracefully
        logger.warning("Document profiling failed: %s", type(exc).__name__)
        return {}
    subject = str(data.get("subject", "")).strip()
    summary = str(data.get("summary", "")).strip()
    if not (subject or summary):
        return {}
    profile = {"subject": subject, "summary": summary}
    for field in ("language", "domain", "content_style", "reasoning_style"):
        value = str(data.get(field, "")).strip()
        if value:
            profile[field] = value
    for field in (
        "definitions_and_terminology",
        "chronology_signals",
        "quantitative_signals",
        "process_signals",
        "structured_data_signals",
        "example_signals",
        "code_signals",
        "visual_dependencies",
        "supported_question_types",
        "source_quality_warnings",
    ):
        values = data.get(field)
        if isinstance(values, list):
            cleaned = [str(value).strip() for value in values if str(value).strip()]
            if cleaned:
                profile[field] = cleaned[:12]
    return profile


def profile_to_summary(profile: dict | None) -> str:
    """Flatten a profile dict into the single guidance string passed to MAP/REDUCE."""
    profile = profile or {}
    parts = [
        profile.get("subject", ""),
        profile.get("language", ""),
        profile.get("domain", ""),
        profile.get("content_style", ""),
        profile.get("reasoning_style", ""),
        profile.get("summary", ""),
    ]
    signal_fields = {
        "definitions_and_terminology": "Definitions/terms",
        "chronology_signals": "Chronology",
        "quantitative_signals": "Quantitative material",
        "process_signals": "Processes/causality",
        "structured_data_signals": "Tables/data",
        "example_signals": "Examples/cases",
        "code_signals": "Code",
        "visual_dependencies": "Visual dependencies",
        "supported_question_types": "Supported question types",
    }
    for field, label in signal_fields.items():
        values = profile.get(field) or []
        if values:
            parts.append(f"{label}: " + ", ".join(map(str, values)))
    warnings = profile.get("source_quality_warnings") or []
    if warnings:
        parts.append("Source cautions: " + ", ".join(map(str, warnings)))
    return " ".join(p for p in parts if p).strip()
