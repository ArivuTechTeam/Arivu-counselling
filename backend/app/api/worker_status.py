"""Super-admin-only durable-worker health endpoint.

Surfaces whether the faculty worker process is alive and draining the queue, so
a stalled/absent worker (jobs silently stuck in ``queued``) is visible to ops
instead of presenting as an indefinite spinner. Returns only counts/ages — never
tenant content.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.worker_health import worker_health

router = APIRouter(prefix="/api/v1/platform", tags=["super-admin"])


def _require_super(profile: CurrentProfile) -> None:
    if profile.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admins only.")


@router.get("/worker-health")
def get_worker_health(
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_super(profile)
    return worker_health(get_service_client(), get_settings())
