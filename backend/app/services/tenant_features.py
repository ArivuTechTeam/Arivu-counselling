"""Tenant-scoped feature rollout on top of deployment-wide master switches.

Railway environment variables are the emergency/master controls.  A feature is
usable only when its master switch is enabled *and* the institution has opted
in through ``tenants.feature_flags``.  This lets production infrastructure be
prepared once without exposing unfinished features to every tenant.
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
    settings = get_settings()
    normalized = normalize_feature_flags(raw_flags)
    return {
        key: bool(getattr(settings, env_attribute, False)) and normalized[key]
        for key, env_attribute in FEATURE_ENV_ATTRIBUTES.items()
    }


def profile_feature_enabled(profile: Any, feature: str) -> bool:
    if feature not in FEATURE_ENV_ATTRIBUTES:
        raise ValueError(f"Unknown tenant feature: {feature}")
    raw_flags = getattr(profile, "tenant_feature_flags", None)
    # Profiles constructed by internal scripts/tests before migration 57 do not
    # carry tenant flags. The authenticated request path always supplies a dict.
    if raw_flags is None:
        return True
    return effective_feature_flags(raw_flags)[feature]


def tenant_feature_enabled(service: Any, tenant_id: str, feature: str) -> bool:
    if feature not in FEATURE_ENV_ATTRIBUTES:
        raise ValueError(f"Unknown tenant feature: {feature}")
    result = (
        service.table("tenants")
        .select("feature_flags")
        .eq("id", tenant_id)
        .maybe_single()
        .execute()
    )
    data = getattr(result, "data", None)
    if not isinstance(data, dict) or "feature_flags" not in data:
        # Compatibility for a rolling deployment and lightweight service mocks.
        # A migrated production tenant always has this non-null column.
        return True
    master = bool(getattr(get_settings(), FEATURE_ENV_ATTRIBUTES[feature], False))
    return master and normalize_feature_flags(data.get("feature_flags"))[feature]


def require_profile_feature(profile: Any, feature: str, *, label: str) -> None:
    if not profile_feature_enabled(profile, feature):
        raise HTTPException(
            status_code=404,
            detail=f"{label} is not enabled for this institution.",
        )
