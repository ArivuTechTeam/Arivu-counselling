"""Authenticated account-security actions."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
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
        raise public_error(
            400,
            "We couldn't change your password. Please try again.",
            operation="change password",
            exception=exc,
        ) from exc

    try:
        service.table("profiles").update({"must_change_password": False}).eq(
            "id", profile.user_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        # During a rolling deployment the column may not exist yet. That is
        # harmless for accounts that were never under the authoritative gate.
        if profile.must_change_password:
            raise public_error(
                500,
                "Your password changed, but we couldn't finish unlocking your account. "
                "Please contact your administrator.",
                operation="clear temporary-password requirement",
                exception=exc,
            ) from exc
    return {"changed": True}
