"""Student feedback and role-scoped support inboxes.

Routing is derived on the server. Browser input never selects a destination,
tenant, student identity, or ticket status.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/contact", tags=["student contact"])

Kind = Literal["feedback", "support"]
Category = Literal["general", "feature_idea", "course_access", "quiz_issue", "app_bug"]
Route = Literal["platform", "institution"]
Status = Literal["open", "answered", "closed"]

_STUDENT_FIELDS = "reference,kind,category,routed_to,message,rating,status,reply,created_at,updated_at"
_STAFF_FIELDS = _STUDENT_FIELDS + ",tenant:tenants!student_contact_requests_tenant_id_fkey(name)"


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


class ContactReceipt(BaseModel):
    reference: str
    routed_to: Route
    status: Status


def _route(kind: Kind, category: Category, rating: int | None) -> Route:
    if kind == "feedback":
        if category not in {"general", "feature_idea", "app_bug"}:
            raise HTTPException(422, "Choose a feedback category.")
        return "platform"
    if category not in {"course_access", "quiz_issue", "app_bug"}:
        raise HTTPException(422, "Choose a support issue category.")
    if rating is not None:
        raise HTTPException(422, "Ratings are only available for app feedback.")
    return "platform" if category == "app_bug" else "institution"


def _staff_scope(profile: CurrentProfile) -> tuple[str, str | None]:
    if profile.role == "super_admin":
        return "platform", None
    if profile.role == "institution_admin":
        return "institution", profile.tenant_id
    raise HTTPException(403, "Support inbox is for administrators only.")


def _contact_out(row: dict) -> ContactOut:
    tenant = row.get("tenant")
    return ContactOut(
        **{field: row.get(field) for field in ContactOut.model_fields if field != "institution_name"},
        institution_name=tenant.get("name") if isinstance(tenant, dict) else None,
    )


@router.post("", response_model=ContactReceipt, status_code=201)
def submit_contact(
    payload: ContactCreate,
    profile: CurrentProfile = Depends(get_current_profile),
) -> ContactReceipt:
    if profile.role != "student":
        raise HTTPException(403, "Only students can submit this form.")
    destination = _route(payload.kind, payload.category, payload.rating)
    service = get_service_client()
    # A modest server-side cooldown discourages accidental doubles and spam.
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    recent = (
        service.table("student_contact_requests")
        .select("reference")
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
        .data
        or []
    )
    if recent:
        raise HTTPException(429, "Please wait a minute before sending another request.")
    row = {
        "reference": uuid4().hex[:12].upper(),
        "tenant_id": profile.tenant_id,
        "student_id": profile.user_id,
        "kind": payload.kind,
        "category": payload.category,
        "routed_to": destination,
        "message": payload.message,
        "rating": payload.rating,
    }
    result = (
        service.table("student_contact_requests")
        .insert(row)
        .select("reference,routed_to,status")
        .execute()
    )
    if not result.data:
        raise HTTPException(503, "Request could not be saved. Please try again.")
    return ContactReceipt(**result.data[0])


@router.get("/mine", response_model=list[ContactOut])
def my_contacts(profile: CurrentProfile = Depends(get_current_profile)) -> list[ContactOut]:
    if profile.role != "student":
        raise HTTPException(403, "Only students can view their requests.")
    rows = (
        get_service_client().table("student_contact_requests")
        .select(_STUDENT_FIELDS)
        .eq("tenant_id", profile.tenant_id)
        .eq("student_id", profile.user_id)
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
