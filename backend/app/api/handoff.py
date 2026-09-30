"""Short-lived, one-way handoff from quiz-generator to ArivuPro ExamApp."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/handoff", tags=["handoff"])
HANDOFF_EVENT_TYPE = "handoff.examapp.minted"
HANDOFF_TTL_SECONDS = 60
ALLOWED_ROLES = {"student", "teacher", "institution_admin", "super_admin"}


class ExamAppHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next: str = "/"

    @field_validator("next")
    @classmethod
    def validate_next(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or "\\" in value
            or any(character in value for character in ("\r", "\n", "\x00"))
        ):
            raise ValueError("next must be a relative path beginning with a single '/'.")
        return value


class ExamAppHandoffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redirect_url: str


def _load_tenant_handoff_settings(profile: CurrentProfile) -> tuple[bool, str | None]:
    """Read the dedicated tenant column directly, bypassing general flags."""
    if profile.role == "super_admin":
        return True, None

    result = (
        get_service_client()
        .table("tenants")
        .select("name,handwritten_evaluation_enabled")
        .eq("id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This institution is not available.",
        )
    return bool(result.data.get("handwritten_evaluation_enabled", False)), result.data.get(
        "name"
    )


def _student_exam_context(profile: CurrentProfile) -> dict[str, str]:
    """Best-effort global-catalog mapping for student-only ExamApp claims."""
    if profile.role != "student":
        return {}

    claims: dict[str, str] = {}
    try:
        service = get_service_client()
        enrollments = (
            service.table("enrollments")
            .select("course_id,course_level_id")
            .eq("tenant_id", profile.tenant_id)
            .eq("profile_id", profile.user_id)
            .execute()
            .data
            or []
        )
        if not enrollments:
            return claims
        enrollment = enrollments[0]

        course_result = (
            service.table("courses")
            .select("catalog_course_id")
            .eq("tenant_id", profile.tenant_id)
            .eq("id", enrollment["course_id"])
            .maybe_single()
            .execute()
        )
        course = course_result.data if course_result is not None else None
        catalog_course_id = course.get("catalog_course_id") if course else None
        if not catalog_course_id:
            return claims

        catalog_course_result = (
            service.table("catalog_courses")
            .select("code")
            .eq("id", catalog_course_id)
            .maybe_single()
            .execute()
        )
        catalog_course = (
            catalog_course_result.data if catalog_course_result is not None else None
        )
        exam_type = str(catalog_course.get("code") or "").strip() if catalog_course else ""
        if not exam_type:
            return claims
        claims["exam_type"] = exam_type

        course_level_id = enrollment.get("course_level_id")
        if not course_level_id:
            return claims
        level_result = (
            service.table("course_levels")
            .select("catalog_level_id")
            .eq("tenant_id", profile.tenant_id)
            .eq("course_id", enrollment["course_id"])
            .eq("id", course_level_id)
            .maybe_single()
            .execute()
        )
        level = level_result.data if level_result is not None else None
        catalog_level_id = level.get("catalog_level_id") if level else None
        if not catalog_level_id:
            return claims

        catalog_level_result = (
            service.table("catalog_course_levels")
            .select("name,catalog_course_id")
            .eq("id", catalog_level_id)
            .maybe_single()
            .execute()
        )
        catalog_level = (
            catalog_level_result.data if catalog_level_result is not None else None
        )
        if not catalog_level or str(catalog_level.get("catalog_course_id")) != str(
            catalog_course_id
        ):
            return claims
        exam_level = str(catalog_level.get("name") or "").strip()
        if exam_level:
            claims["exam_level"] = exam_level
    except Exception as exc:  # noqa: BLE001 - optional enrichment must fail open
        logger.warning(
            "ExamApp student catalog context unavailable error_type=%s",
            type(exc).__name__,
        )
    return claims


@router.post("/examapp", response_model=ExamAppHandoffResponse)
def create_examapp_handoff(
    body: ExamAppHandoffRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> ExamAppHandoffResponse:
    """Mint a 60-second ExamApp token from authoritative profile data."""
    if profile.role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account role cannot use ExamApp.",
        )

    enabled, tenant_name = _load_tenant_handoff_settings(profile)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Handwritten evaluation is not enabled for this institution.",
        )

    settings = get_settings()
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)
    tenant_id = None if profile.role == "super_admin" else profile.tenant_id
    claims: dict[str, str | int | None] = {
        "iss": "quiz-generator",
        "aud": "examapp",
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=HANDOFF_TTL_SECONDS)).timestamp()),
        "jti": str(uuid4()),
        "sub": profile.user_id,
        "email": profile.email,
        "name": profile.full_name,
        "role": profile.role,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
    }
    claims.update(_student_exam_context(profile))
    token = jwt.encode(claims, settings.handoff_shared_secret, algorithm="HS256")

    # This write is part of a successful mint: it deliberately contains no
    # token or redirect URL. The service-role client is scoped with the
    # authoritative profile tenant, including the platform tenant for admins.
    get_service_client().table("events").insert(
        {
            "tenant_id": profile.tenant_id,
            "actor_id": profile.user_id,
            "actor_role": profile.role,
            "event_type": HANDOFF_EVENT_TYPE,
            "subject_type": "examapp_handoff",
            "metadata": {"next": body.next},
        }
    ).execute()

    redirect_url = (
        f"{settings.examapp_frontend_url}/auth/handoff"
        f"#token={quote(token, safe='')}&next={quote(body.next, safe='/')}"
    )
    return ExamAppHandoffResponse(redirect_url=redirect_url)
