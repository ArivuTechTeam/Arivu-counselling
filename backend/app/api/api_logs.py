"""Super-admin-only AI provider request observability endpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/platform", tags=["super-admin"])
MAX_PAGE_SIZE = 100


class ApiCallLogSummary(BaseModel):
    id: str
    tenant_id: str | None = None
    document_id: str | None = None
    document_name: str | None = None
    job_id: str | None = None
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


class ApiCallLogDetail(ApiCallLogSummary):
    raw_request: Any
    raw_response: Any = None


class ApiCallLogPage(BaseModel):
    items: list[ApiCallLogSummary]
    page: int
    page_size: int
    total: int


class ApiCallLogTotals(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thinking_tokens: int
    cost_usd: float
    cost_inr: float
    call_count: int
    call_types: list[str]


class ApiCallLogDocument(BaseModel):
    document_id: str
    document_name: str | None = None
    summary: ApiCallLogTotals
    items: list[ApiCallLogSummary]


def _require_super(profile: CurrentProfile) -> None:
    if profile.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admins only.")


def _number(value: object) -> float | None:
    return float(value) if value is not None else None


def _summary(row: dict) -> dict:
    document = row.pop("documents", None) or {}
    row["document_name"] = document.get("original_filename")
    row["cost_usd"] = _number(row.get("cost_usd"))
    row["cost_inr"] = _number(row.get("cost_inr"))
    return row


@router.get("/api-logs", response_model=ApiCallLogPage)
def list_api_logs(
    profile: CurrentProfile = Depends(get_current_profile),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    tenant_id: str | None = None,
    document_id: str | None = None,
    call_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    _require_super(profile)
    query = get_service_client().table("api_call_logs").select(
        "id,tenant_id,document_id,job_id,call_type,provider,model,was_fallback,"
        "input_tokens,output_tokens,cached_tokens,thinking_tokens,cost_usd,cost_inr,"
        "latency_ms,status,error_message,created_at,documents(original_filename)",
        count="exact",
    )
    for field, value in (("tenant_id", tenant_id), ("document_id", document_id),
                         ("call_type", call_type), ("provider", provider), ("status", status)):
        if value:
            query = query.eq(field, value)
    if date_from:
        query = query.gte("created_at", date_from.isoformat())
    if date_to:
        query = query.lte("created_at", date_to.isoformat())
    result = query.order("created_at", desc=True).range(
        (page - 1) * page_size, page * page_size - 1
    ).execute()
    return {"items": [_summary(dict(row)) for row in (result.data or [])],
            "page": page, "page_size": page_size, "total": result.count or 0}


@router.get("/api-logs/{log_id}", response_model=ApiCallLogDetail)
def get_api_log(
    log_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_super(profile)
    result = get_service_client().table("api_call_logs").select(
        "*,documents(original_filename)"
    ).eq("id", log_id).maybe_single().execute()
    if not result or not result.data:
        raise HTTPException(status_code=404, detail="API call log not found.")
    return _summary(dict(result.data))


@router.get("/api-logs/by-document/{document_id}", response_model=ApiCallLogDocument)
def api_logs_by_document(
    document_id: str, profile: CurrentProfile = Depends(get_current_profile)
) -> dict:
    _require_super(profile)
    result = get_service_client().table("api_call_logs").select(
        "id,tenant_id,document_id,job_id,call_type,provider,model,was_fallback,"
        "input_tokens,output_tokens,cached_tokens,thinking_tokens,cost_usd,cost_inr,"
        "latency_ms,status,error_message,created_at,documents(original_filename)"
    ).eq("document_id", document_id).order("created_at", desc=True).execute()
    items = [_summary(dict(row)) for row in (result.data or [])]
    totals = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
              "thinking_tokens": 0, "cost_usd": Decimal(0), "cost_inr": Decimal(0)}
    for item in items:
        for field in ("input_tokens", "output_tokens", "cached_tokens", "thinking_tokens"):
            totals[field] += item.get(field) or 0
        totals["cost_usd"] += Decimal(str(item.get("cost_usd") or 0))
        totals["cost_inr"] += Decimal(str(item.get("cost_inr") or 0))
    return {"document_id": document_id, "document_name": items[0].get("document_name") if items else None,
            "summary": {**totals, "cost_usd": float(totals["cost_usd"]),
                        "cost_inr": float(totals["cost_inr"]), "call_count": len(items),
                        "call_types": sorted({item["call_type"] for item in items})},
            "items": items}
