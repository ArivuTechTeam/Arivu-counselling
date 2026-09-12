"""Authenticated account-security actions."""

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.supabase import create_anon_auth_client, get_service_client
from app.services.account_deletion import erase_account_data

router = APIRouter(prefix="/api/v1/auth", tags=["account"])
_account_bearer = HTTPBearer(auto_error=True)

# A tiny denylist of obvious choices — not exhaustive, just stops the worst.
_COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "12345678",
    "123456789",
    "1234567890",
    "qwerty123",
    "qwertyuiop",
    "admin123",
    "welcome1",
    "welcome123",
    "iloveyou",
    "letmein1",
    "changeme",
    "passw0rd",
}


def _validate_new_password(new: str, current: str, email: str | None) -> None:
    """Server-side strength gate — the authoritative one (never trust the
    client). Strong policy: >= 8 chars with upper, lower and a number; different
    from the current password; not the email; not an obvious common password.
    Raises HTTPException(400) with a human message on the first failing rule.
    """
    if len(new) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if len(new) > 128:
        raise HTTPException(400, "Password is too long (max 128 characters).")
    if not re.search(r"[A-Z]", new):
        raise HTTPException(400, "Password must include an uppercase letter.")
    if not re.search(r"[a-z]", new):
        raise HTTPException(400, "Password must include a lowercase letter.")
    if not re.search(r"[0-9]", new):
        raise HTTPException(400, "Password must include a number.")
    if new == current:
        raise HTTPException(
            400, "New password must be different from your current one."
        )
    if email:
        cleaned = email.strip().lower()
        if new.strip().lower() == cleaned:
            raise HTTPException(400, "Password must not be your email address.")
        local = cleaned.split("@", 1)[0]
        if len(local) >= 3 and local in new.lower():
            raise HTTPException(400, "Password must not contain your email name.")
    if new.lower() in _COMMON_PASSWORDS:
        raise HTTPException(
            400, "That password is too common — pick something less guessable."
        )


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class AccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(pattern=r"^DELETE$")


class AccountDeletionResult(BaseModel):
    deleted: bool


@router.post("/change-password")
def change_password(
    body: PasswordChange,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict[str, bool]:
    """Change the password (after verifying the current one) and clear the
    authoritative first-login block."""
    if not profile.email:
        raise HTTPException(status_code=400, detail="This account has no email on file.")

    # 1) Authenticate the CURRENT password. This proves it's really them (not a
    #    borrowed/left-open session) and lets us enforce "new != old".
    # sign_in mutates the Supabase client's session/Authorization header, so this
    # password check must not use the process-wide stateless anon singleton.
    anon = create_anon_auth_client()
    try:
        anon.auth.sign_in_with_password(
            {"email": profile.email, "password": body.current_password}
        )
    except Exception:  # noqa: BLE001 - any failure means the current password was wrong
        raise HTTPException(
            status_code=400, detail="Your current password is incorrect."
        )

    # 2) Strong-policy validation (server-side is the source of truth).
    _validate_new_password(body.password, body.current_password, profile.email)

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
        ).eq("tenant_id", profile.tenant_id).execute()
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


@router.delete("/account", response_model=AccountDeletionResult)
def delete_own_account(
    _body: AccountDeletion,
    credentials: HTTPAuthorizationCredentials = Depends(_account_bearer),
    profile: CurrentProfile = Depends(get_current_profile),
) -> AccountDeletionResult:
    """Revoke every session, erase personal activity, and delete Auth identity.

    Institution-owned teaching content is retained without author identifiers.
    Migration 30 owns the atomic database anonymization and is callable only by
    the backend service role.
    """
    service = get_service_client()

    try:
        service.auth.admin.sign_out(credentials.credentials, scope="global")
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            503,
            "We couldn't securely sign out this account. Please try again.",
            operation="revoke sessions before account deletion",
            exception=exc,
        ) from exc

    try:
        erase_account_data(
            service,
            user_id=profile.user_id,
            tenant_id=profile.tenant_id,
        )
        service.auth.admin.delete_user(profile.user_id)
    except Exception as exc:  # noqa: BLE001
        raise public_error(
            503,
            "We couldn't finish deleting this account. Please contact support with the error reference.",
            operation="delete account data",
            exception=exc,
        ) from exc

    return AccountDeletionResult(deleted=True)
