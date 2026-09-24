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
    normalize_feature_flags,
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


def test_effective_flags_require_master_and_tenant_opt_in():
    with patch(
        "app.services.tenant_features.get_settings",
        return_value=_settings(batches_enabled=True, quiz_reuse_enabled=True),
    ):
        flags = effective_feature_flags({"batches": True, "commerce_pack": True})
    assert flags["batches"] is True
    assert flags["quiz_reuse"] is False
    assert flags["commerce_pack"] is False
    assert set(flags) == set(FEATURE_KEYS)


def test_authenticated_profile_uses_persisted_tenant_flags():
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
        assert profile_feature_enabled(profile, "batches") is False


def test_feature_payload_rejects_unknown_keys_and_normalizes_missing_keys():
    with pytest.raises(ValidationError):
        TenantUpdate(feature_flags={"unknown": True})
    update = TenantUpdate(feature_flags={"batches": True})
    assert update.feature_flags == normalize_feature_flags({"batches": True})


def test_migration_is_rerunnable_and_blocks_disabled_batch_membership():
    migration = (
        Path(__file__).parents[2]
        / "migrations"
        / "migration-57-tenant-feature-rollout.sql"
    ).read_text(encoding="utf-8").lower()
    assert "add column if not exists feature_flags" in migration
    assert "drop trigger if exists enforce_batch_feature_on_memberships" in migration
    assert "before insert or update on public.batch_memberships" in migration
    assert "feature_flags->>'batches'" in migration
