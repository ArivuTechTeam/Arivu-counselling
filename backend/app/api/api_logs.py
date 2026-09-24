"""Super-admin-only AI provider request observability endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.role_checks import require_super_admin
from app.lib.supabase import get_service_client

router = APIRouter(prefix="/api/v1/platform", tags=["super-admin"])
MAX_PAGE_SIZE = 100


class ApiCallLogSummary(BaseModel):
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
    row["cost_usd"] = _number(row.get("cost_usd"))
    row["cost_inr"] = _number(row.get("cost_inr"))
    return row


@router.get("/api-logs", response_model=ApiCallLogPage)
def list_api_logs(
    profile: CurrentProfile = Depends(get_current_profile),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    call_type: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    require_super_admin(profile)
    query = get_service_client().table("api_call_logs").select(
        "call_type,provider,model,was_fallback,"
        "input_tokens,output_tokens,cached_tokens,thinking_tokens,cost_usd,cost_inr,"
        "latency_ms,status,error_message,created_at",
        count="exact",
    )
    for field, value in (("call_type", call_type), ("provider", provider), ("status", status)):
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
