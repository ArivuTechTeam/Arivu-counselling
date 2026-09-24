from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.api.admin import TenantUpdate
from app.lib.auth import CurrentProfile
from app.services.tenant_features import (
    FEATURE_KEYS,
    effective_feature_flags,
    profile_feature_enabled,
)


def _settings(**enabled):
    values = {
        "faculty_jobs_enabled": False,
        "quiz_reuse_enabled": False,
        "batches_enabled": False,
        "scoring_policies_enabled": False,
        "commerce_pack_enabled": False,
        "figure_attach_enabled": False,
    }
    values.update(enabled)
    return SimpleNamespace(**values)


def test_effective_flags_follow_platform_master_switches_for_every_tenant():
    with patch(
        "app.services.tenant_features.get_settings",
        return_value=_settings(batches_enabled=True, quiz_reuse_enabled=True),
    ):
        flags = effective_feature_flags({"batches": False, "commerce_pack": True})
    assert flags["batches"] is True
    assert flags["quiz_reuse"] is True
    assert flags["commerce_pack"] is False
    assert set(flags) == set(FEATURE_KEYS)


def test_authenticated_profile_cannot_disable_platform_feature_per_tenant():
    profile = CurrentProfile(
        user_id="teacher",
        tenant_id="tenant",
        role="teacher",
        tenant_feature_flags={"batches": False},
    )
    with patch(
        "app.services.tenant_features.get_settings",
        return_value=_settings(batches_enabled=True),
    ):
        assert profile_feature_enabled(profile, "batches") is True


def test_institution_update_rejects_per_tenant_feature_overrides():
    with pytest.raises(ValidationError):
        TenantUpdate(feature_flags={"batches": False})


def test_commerce_defaults_migration_is_rerunnable_and_removes_tenant_gate():
    migration = (
        Path(__file__).parents[2]
        / "migrations"
        / "migration-58-commerce-platform-defaults.sql"
    ).read_text(encoding="utf-8").lower()
    assert "drop trigger if exists enforce_batch_feature_on_memberships" in migration
    assert "drop function if exists public.enforce_batch_feature_enabled()" in migration
    assert "alter column feature_flags set default" in migration
    for feature in FEATURE_KEYS:
        assert f"'{feature}', true" in migration
