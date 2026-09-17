"""Public API error helpers that never expose internal exception text."""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger("app.api")

_AUTH_ERROR_MESSAGES: dict[str, tuple[int, str]] = {
    "email_exists": (
        409,
        "An account with this email address already exists. Use a different email address.",
    ),
    "user_already_exists": (
        409,
        "An account with this email address already exists. Use a different email address.",
    ),
    "weak_password": (
        400,
        "The temporary password does not meet the current password requirements. Generate a new password and try again.",
    ),
    "email_address_invalid": (400, "Enter a valid administrator email address."),
    "validation_failed": (400, "Check the administrator account details and try again."),
    "over_request_rate_limit": (
        429,
        "Too many account-creation attempts. Wait a few minutes and try again.",
    ),
}


def public_error(
    status_code: int,
    detail: str,
    *,
    operation: str,
    exception: Exception,
) -> HTTPException:
    """Record a safe diagnostic and return a client-facing HTTP error.

    Database/provider exception strings can contain schema details, upstream
    response fragments, or user content. Log only the operation and exception
    class; keep the stable, friendly detail in the response payload.
    """
    logger.warning(
        "API operation failed: %s (%s)",
        operation,
        type(exception).__name__,
    )
    return HTTPException(status_code=status_code, detail=detail)


def auth_provisioning_error(
    exception: Exception,
    *,
    operation: str,
) -> HTTPException:
    """Translate stable Supabase Auth codes without exposing provider messages."""
    raw_code = getattr(exception, "code", None)
    code = raw_code if isinstance(raw_code, str) else None
    raw_status = getattr(exception, "status", None)
    provider_status = raw_status if isinstance(raw_status, int) else None
    logger.warning(
        "Auth provisioning failed: %s (%s, code=%s, status=%s)",
        operation,
        type(exception).__name__,
        code or "unknown",
        provider_status if provider_status is not None else "unknown",
    )

    mapped = _AUTH_ERROR_MESSAGES.get(code or "")
    if mapped is not None:
        status_code, detail = mapped
        headers = {"Retry-After": "60"} if status_code == 429 else None
        return HTTPException(status_code=status_code, detail=detail, headers=headers)

    if provider_status is not None and provider_status >= 500:
        return HTTPException(
            status_code=503,
            detail="The account service could not create the administrator right now. Please try again shortly.",
        )

    return HTTPException(
        status_code=400,
        detail="The administrator account could not be created. Check the email address and generate a new temporary password.",
    )
