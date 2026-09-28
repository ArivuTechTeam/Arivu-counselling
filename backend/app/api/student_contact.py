"""Role-aware feedback and tenant-scoped support inboxes.

Routing is derived on the server. Browser input never selects a destination,
tenant, requester identity/role, or ticket status.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/contact", tags=["support contact"])

Kind = Literal["feedback", "support"]
Category = Literal[
    "general",
    "feature_idea",
    "general_support",
    "course_access",
    "quiz_issue",
    "app_bug",
]
Route = Literal["platform", "institution"]
Status = Literal["open", "answered", "closed"]
RequesterRole = Literal["student", "teacher", "institution_admin"]

_REQUESTER_FIELDS = (
    "reference,requester_role,kind,category,routed_to,message,rating,status,"
    "reply,created_at,updated_at"
)
_STAFF_FIELDS = (
    _REQUESTER_FIELDS
    + ",tenant:tenants!student_contact_requests_tenant_id_fkey(name)"
    + ",requester:profiles!student_contact_requests_requester_tenant_fkey(full_name)"
)


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Kind
    category: Category
    message: str = Field(min_length=10, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("message")
    @classmethod
    def message_has_content(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Please provide at least 10 characters.")
        return value


class ContactReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=4000)
    status: Literal["answered", "closed"] = "answered"

    @field_validator("reply")
    @classmethod
    def reply_has_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please write a reply.")
        return value


class ContactOut(BaseModel):
    reference: str
    requester_role: RequesterRole
    kind: Kind
    category: Category
    routed_to: Route
    message: str
    rating: int | None = None
    status: Status
    reply: str | None = None
    created_at: datetime
    updated_at: datetime
    institution_name: str | None = None
    requester_name: str | None = None


class ContactReceipt(BaseModel):
    reference: str
    routed_to: Route
    status: Status


def _route(
    role: RequesterRole,
    kind: Kind,
    category: Category,
    rating: int | None,
) -> Route:
    if kind == "feedback":
        if category not in {"general", "feature_idea", "app_bug"}:
            raise HTTPException(422, "Choose a feedback category.")
        return "platform"
    if category not in {"general_support", "course_access", "quiz_issue", "app_bug"}:
        raise HTTPException(422, "Choose a support issue category.")
    if rating is not None:
        raise HTTPException(422, "Ratings are only available for app feedback.")
    if role == "student" and category in {"course_access", "quiz_issue"}:
        return "institution"
    return "platform"


def _staff_scope(profile: CurrentProfile) -> tuple[str, str | None]:
    if profile.role == "super_admin":
        return "platform", None
    if profile.role == "institution_admin":
        return "institution", profile.tenant_id
    raise HTTPException(403, "Support inbox is for administrators only.")


def _contact_out(row: dict) -> ContactOut:
    tenant = row.get("tenant")
    requester = row.get("requester")
    return ContactOut(
        **{
            field: row.get(field)
            for field in ContactOut.model_fields
            if field not in {"institution_name", "requester_name"}
        },
        institution_name=tenant.get("name") if isinstance(tenant, dict) else None,
        requester_name=(
            requester.get("full_name") if isinstance(requester, dict) else None
        ),
    )


@router.post("", response_model=ContactReceipt, status_code=201)
def submit_contact(
    payload: ContactCreate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> ContactReceipt:
    if profile.role not in {"student", "teacher", "institution_admin"}:
        raise HTTPException(403, "This account cannot submit support requests.")
    requester_role = cast(RequesterRole, profile.role)
    destination = _route(
        requester_role, payload.kind, payload.category, payload.rating
    )
    try:
        result = get_service_client().rpc(
            "submit_contact_request",
            {
                "p_tenant_id": profile.tenant_id,
                "p_requester_id": profile.user_id,
                "p_requester_role": requester_role,
                "p_reference": uuid4().hex[:12].upper(),
                "p_kind": payload.kind,
                "p_category": payload.category,
                "p_routed_to": destination,
                "p_message": payload.message,
                "p_rating": payload.rating,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - never expose provider response bodies
        raise public_error(
            503,
            "Request could not be saved. Please try again.",
            operation="submit support contact request",
            exception=exc,
        ) from exc
    row = result.data
    if not isinstance(row, dict) or not isinstance(row.get("allowed"), bool):
        raise HTTPException(503, "Request could not be saved. Please try again.")
    if not row["allowed"]:
        retry_after = max(1, int(row.get("retry_after_seconds") or 1))
        raise HTTPException(
            429,
            "Please wait a minute before sending another request.",
            headers={"Retry-After": str(retry_after)},
        )
    return ContactReceipt.model_validate(row)


@router.get("/mine", response_model=list[ContactOut])
def my_contacts(profile: CurrentProfile = Depends(get_current_profile)) -> list[ContactOut]:
    if profile.role not in {"student", "teacher", "institution_admin"}:
        raise HTTPException(403, "This account does not have a support outbox.")
    rows = (
        get_service_client().table("student_contact_requests")
        .select(_REQUESTER_FIELDS)
        .eq("tenant_id", profile.tenant_id)
        .eq("requester_id", profile.user_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )
    return [_contact_out(row) for row in rows]


@router.get("/inbox", response_model=list[ContactOut])
def support_inbox(profile: CurrentProfile = Depends(get_current_profile)) -> list[ContactOut]:
    destination, tenant_id = _staff_scope(profile)
    query = (
        get_service_client().table("student_contact_requests")
        .select(_STAFF_FIELDS)
        .eq("routed_to", destination)
    )
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    rows = query.order("created_at", desc=True).limit(100).execute().data or []
    return [_contact_out(row) for row in rows]


@router.post("/inbox/{reference}/reply", response_model=ContactOut)
def reply_to_contact(
    reference: str,
    payload: ContactReply,
    profile: CurrentProfile = Depends(get_current_profile),
) -> ContactOut:
    if len(reference) != 12 or not reference.isalnum():
        raise HTTPException(404, "Request not found.")
    destination, tenant_id = _staff_scope(profile)
    query = (
        get_service_client().table("student_contact_requests")
        .update({
            "reply": payload.reply,
            "status": payload.status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("reference", reference)
        .eq("routed_to", destination)
    )
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    result = query.select(_STAFF_FIELDS).execute()
    if not result.data:
        raise HTTPException(404, "Request not found.")
    return _contact_out(result.data[0])
