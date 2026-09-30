"""Super-admin-only, metadata-only AI provider observability endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_super_admin
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/platform", tags=["super-admin"])
MAX_PAGE_SIZE = 100


class ApiCallLogSummary(BaseModel):
    id: str
    tenant_id: str | None = None
    document_id: str | None = None
    job_id: str | None = None
    evaluation_job_id: str | None = None
    workflow_id: str | None = None
    call_type: str
    provider: Literal["gemini", "deepseek"]
    model: str
    was_fallback: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    thinking_tokens: int | None = None
    cost_usd: float | None = None
    cost_inr: float | None = None
    latency_ms: int
    status: Literal["success", "error"]
    error_message: str | None = None
    created_at: datetime


class ApiCallLogPage(BaseModel):
    items: list[ApiCallLogSummary]
    page: int
    page_size: int
    total: int


def _number(value: object) -> float | None:
    return float(value) if value is not None else None


def _summary(row: dict) -> dict:
    # Legacy error text may contain provider payloads. Never disclose it.
    row["error_message"] = (
        "Provider call failed. Check provider availability and configuration."
        if row.get("status") == "error" else None
    )
    row["cost_usd"] = _number(row.get("cost_usd"))
    row["cost_inr"] = _number(row.get("cost_inr"))
    return row


@router.get("/api-logs", response_model=ApiCallLogPage)
def list_api_logs(
    profile: CurrentProfile = Depends(get_current_profile),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    tenant_id: UUID | None = None,
    document_id: UUID | None = None,
    workflow_id: UUID | None = None,
    evaluation_job_id: UUID | None = None,
    legacy_only: bool = False,
    unlinked_only: bool = False,
    platform_only: bool = False,
    call_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    require_super_admin(profile)
    query = get_service_client().table("api_call_logs").select(
        "id,tenant_id,document_id,job_id,evaluation_job_id,workflow_id,call_type,provider,model,was_fallback,"
        "input_tokens,output_tokens,cached_tokens,thinking_tokens,cost_usd,cost_inr,"
        "latency_ms,status,error_message,created_at",
        count="exact",
    )
    for field, value in (("tenant_id", tenant_id), ("document_id", document_id),
                         ("workflow_id", workflow_id), ("evaluation_job_id", evaluation_job_id),
                         ("call_type", call_type), ("provider", provider), ("status", status)):
        if value:
            query = query.eq(field, str(value))
    if legacy_only:
        query = query.is_("workflow_id", "null")
    if unlinked_only:
        query = query.is_("document_id", "null")
    if platform_only:
        query = query.is_("tenant_id", "null")
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    if date_to:
        query = query.lte("created_at", date_to.isoformat())
    result = query.order("created_at", desc=True).order("id", desc=True).range(
        (page - 1) * page_size, page * page_size - 1
    ).execute()
    return {"items": [_summary(dict(row)) for row in (result.data or [])],
            "page": page, "page_size": page_size, "total": result.count or 0}


class CostStage(BaseModel):
    call_type: str
    calls: int
    cost_usd: float | None


class QuizCostSummary(BaseModel):
    group_key: str
    workflow_id: str | None = None
    tenant_id: str | None = None
    document_id: str | None = None
    quiz_set_id: str | None = None
    quiz_title: str | None = None
    kind: Literal["generation", "extraction", "legacy", "unlinked"]
    status: Literal["running", "completed", "failed", "historical"]
    started_at: datetime
    last_call_at: datetime
    call_count: int
    error_count: int
    unpriced_calls: int
    cost_usd: float | None
    cost_inr: float | None
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cached_tokens: int
    provider_latency_ms: int
    stages: list[CostStage]


class QuizCostPage(BaseModel):
    items: list[QuizCostSummary]
    total: int
    cost_usd: float | None
    call_count: int
    unpriced_calls: int
    page: int
    page_size: int


@router.get("/api-log-workflows", response_model=QuizCostPage)
def quiz_cost_workflows(
    profile: CurrentProfile = Depends(get_current_profile),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    tenant_id: UUID | None = None, document_id: UUID | None = None,
    provider: Literal["gemini", "deepseek"] | None = None,
    status: Literal["success", "error"] | None = None,
    date_from: datetime | None = None, date_to: datetime | None = None,
    kind: Literal["generation", "extraction", "legacy"] | None = None,
) -> dict:
    require_super_admin(profile)
    try:
        result = get_service_client().rpc("ai_quiz_cost_page", {
            "p_page": page, "p_page_size": page_size,
            "p_tenant": str(tenant_id) if tenant_id else None,
            "p_document": str(document_id) if document_id else None,
            "p_provider": provider, "p_status": status,
            "p_from": date_from.isoformat() if date_from else None,
            "p_to": date_to.isoformat() if date_to else None, "p_kind": kind,
        }).execute()
    except Exception:
        raise HTTPException(503, "Cost summaries are unavailable. Check that migration 73 is applied and the database is reachable.") from None
    return {**result.data, "page": page, "page_size": page_size}
