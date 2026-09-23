"""Commerce context resolution for generation (Phase 6.3-B/D).

A course's paper profile - exam body / level / paper / assessment year /
accounting framework - is the single place commerce context lives. It is read
into the generation prompt ONLY when COMMERCE_PACK_ENABLED is on and the course
that owns the subject actually has a profile with at least one field set;
otherwise generation is byte-identical to today.

Resolution is best-effort: any lookup problem degrades to "no context" so a
generation never fails because of this feature.
"""

from __future__ import annotations

from app.lib.config import get_settings

# The profile fields that carry commerce context, in display order.
PROFILE_FIELDS = ("exam_body", "level", "paper", "assessment_year", "framework")


def commerce_context_for_prompt(service, tenant_id: str, subject_id: str) -> str | None:
    """The one-line commerce context for a generation, or None.

    Returns None immediately when the commerce pack is off (no DB read happens),
    so the caller - and the pure payload builder it feeds - is byte-identical to
    today. When on, it resolves the course's paper profile and formats it.
    """
    if not getattr(get_settings(), "commerce_pack_enabled", False):
        return None
    return format_commerce_context(resolve_paper_profile(service, tenant_id, subject_id))


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_paper_profile(service, tenant_id: str, subject_id: str) -> dict | None:
    """The paper profile for the course that owns ``subject_id``, or None.

    Never raises: any lookup problem (missing table, no subject, no course, no
    profile, or an all-blank profile) returns None, so callers simply proceed
    without commerce context.
    """
    try:
        subject = (
            service.table("subjects").select("course_id")
            .eq("id", subject_id).eq("tenant_id", tenant_id).maybe_single().execute()
        )
        course_id = (subject.data or {}).get("course_id") if subject else None
        if not course_id:
            return None
        row = (
            service.table("paper_profiles")
            .select(", ".join(("course_id", *PROFILE_FIELDS)))
            .eq("course_id", course_id).eq("tenant_id", tenant_id)
            .maybe_single().execute()
        )
        data = (row.data if row else None) or None
        if not data or not any(_clean(data.get(field)) for field in PROFILE_FIELDS):
            return None
        return data
    except Exception:  # noqa: BLE001 - best-effort; never block generation
        return None


def format_commerce_context(profile_row: dict | None) -> str | None:
    """A compact one-line context string for the prompt, or None when empty.

    Example: ``exam ICAI Foundation Paper 4; assessment year 2025-26; framework
    Indian GAAP``.
    """
    if not profile_row:
        return None
    exam = " ".join(
        part
        for part in (
            _clean(profile_row.get("exam_body")),
            _clean(profile_row.get("level")),
            _clean(profile_row.get("paper")),
        )
        if part
    )
    bits: list[str] = []
    if exam:
        bits.append(f"exam {exam}")
    year = _clean(profile_row.get("assessment_year"))
    if year:
        bits.append(f"assessment year {year}")
    framework = _clean(profile_row.get("framework"))
    if framework:
        bits.append(f"framework {framework}")
    return "; ".join(bits) or None
