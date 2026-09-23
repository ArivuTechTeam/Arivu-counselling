"""Shared server-side role checks for role-scoped API operations."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.lib.auth import CurrentProfile


def _require_role(
    profile: CurrentProfile,
    expected_role: str,
    *,
    detail: str,
) -> None:
    if profile.role != expected_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def require_teacher(profile: CurrentProfile, *, action: str | None = None) -> None:
    detail = f"Only teachers can {action}." if action else "Teachers only."
    _require_role(profile, "teacher", detail=detail)


def require_institution_admin(
    profile: CurrentProfile,
    *,
    action: str | None = None,
) -> None:
    detail = (
        f"Only institution admins can {action}."
        if action
        else "Institution admins only."
    )
    _require_role(profile, "institution_admin", detail=detail)


def require_super_admin(profile: CurrentProfile) -> None:
    _require_role(profile, "super_admin", detail="Super admins only.")


def require_staff(profile: CurrentProfile, *, action: str | None = None) -> None:
    if profile.role not in {"teacher", "institution_admin", "super_admin"}:
        detail = f"Only staff can {action}." if action else "Staff only."
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
