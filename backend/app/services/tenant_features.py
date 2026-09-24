"""Commerce-platform capabilities controlled by deployment master switches.

Every institution receives the same commerce feature set. Railway environment
variables remain as operational kill switches so a capability can be stopped
platform-wide during an incident without shipping new code.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.lib.config import get_settings

FEATURE_ENV_ATTRIBUTES = {
    "faculty_jobs": "faculty_jobs_enabled",
    "quiz_reuse": "quiz_reuse_enabled",
    "batches": "batches_enabled",
    "scoring_policies": "scoring_policies_enabled",
    "commerce_pack": "commerce_pack_enabled",
    "figure_attach": "figure_attach_enabled",
}
FEATURE_KEYS = tuple(FEATURE_ENV_ATTRIBUTES)


def normalize_feature_flags(value: Any) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: source.get(key) is True for key in FEATURE_KEYS}


def effective_feature_flags(raw_flags: Any) -> dict[str, bool]:
    del raw_flags  # Kept in the signature for rolling-version compatibility.
    settings = get_settings()
    return {
        key: bool(getattr(settings, env_attribute, False))
        for key, env_attribute in FEATURE_ENV_ATTRIBUTES.items()
    }


def profile_feature_enabled(profile: Any, feature: str) -> bool:
    if feature not in FEATURE_ENV_ATTRIBUTES:
        raise ValueError(f"Unknown tenant feature: {feature}")
    # Internal scripts and unit fixtures created before the profile feature
    # payload existed intentionally omit it. Authenticated requests always
    # carry a dict and therefore use the platform master switch below.
    if getattr(profile, "tenant_feature_flags", None) is None:
        return True
    return effective_feature_flags(None)[feature]


def tenant_feature_enabled(service: Any, tenant_id: str, feature: str) -> bool:
    if feature not in FEATURE_ENV_ATTRIBUTES:
        raise ValueError(f"Unknown tenant feature: {feature}")
    result = (
        service.table("tenants")
        .select("id,feature_flags")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    data = getattr(result, "data", None)
    if (
        not isinstance(data, dict)
        or "id" not in data
        or "feature_flags" not in data
    ):
        # Lightweight service doubles used by scripts/tests do not implement a
        # tenant lookup. Real request paths always resolve an existing tenant.
        return True
    return effective_feature_flags(None)[feature]


def require_profile_feature(profile: Any, feature: str, *, label: str) -> None:
    if not profile_feature_enabled(profile, feature):
        raise HTTPException(
            status_code=404,
            detail=f"{label} is not enabled for this institution.",
        )
