"""Authenticated account-security actions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/auth", tags=["account"])


class PasswordChange(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(
    body: PasswordChange,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict[str, bool]:
    """Change the password and clear the authoritative first-login block."""
    service = get_service_client()
    try:
        service.auth.admin.update_user_by_id(
            profile.user_id,
            {
                "password": body.password,
                "user_metadata": {"must_change_password": False},
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not change password: {exc}")

    try:
        service.table("profiles").update({"must_change_password": False}).eq(
            "id", profile.user_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        # During a rolling deployment the column may not exist yet. That is
        # harmless for accounts that were never under the authoritative gate.
        if profile.must_change_password:
            raise HTTPException(
                status_code=500,
                detail=f"Password changed, but the account could not be unlocked: {exc}",
            )
    return {"changed": True}
