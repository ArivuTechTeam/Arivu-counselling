"""Non-blocking, metadata-only observability for AI provider calls."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
from uuid import uuid4
import logging
import threading
import time
from typing import Any, Iterator

from app.config.ai_pricing import MODEL_PRICING
from app.lib.config import get_settings
from app.lib.supabase import get_service_client

logger = logging.getLogger(__name__)

_context: ContextVar[dict[str, str | bool | None]] = ContextVar(
    "ai_call_log_context",
    default={"call_type": "unclassified", "tenant_id": None, "document_id": None,
             "job_id": None, "evaluation_job_id": None},
)


@contextmanager
def ai_call_context(
    call_type: str,
    *,
    tenant_id: str | None = None,
    document_id: str | None = None,
    job_id: str | None = None,
    evaluation_job_id: str | None = None,
) -> Iterator[None]:
    """Attach pipeline ownership to every provider call made in this scope."""
    token = _context.set(
        {
            "workflow_id": _context.get().get("workflow_id"),
            "call_type": call_type,
            "tenant_id": tenant_id,
            "document_id": document_id,
            "job_id": job_id,
            "evaluation_job_id": evaluation_job_id,
        }
    )
    try:
        yield
    finally:
        _context.reset(token)


def track_quiz_workflow(kind: str):
    """Attach a durable, metadata-only cost run to synchronous and worker paths.

    Nested generation helpers share a run. Worker retries reuse their job UUID,
    so retry/fallback costs are not silently omitted from the original run.
    Telemetry failure must never prevent quiz generation.
    """
    def decorate(function):
        parameters = signature(function)

        @wraps(function)
        def tracked(*args, **kwargs):
            if _context.get().get("workflow_id") or not _logging_enabled():
                return function(*args, **kwargs)
            values = parameters.bind_partial(*args, **kwargs).arguments
            job = values.get("job") or {}
            profile = values.get("profile")
            tenant = getattr(profile, "tenant_id", None) or values.get("tenant_id") or job.get("tenant_id")
            document = values.get("document_id") or values.get("source_document_id") or (job.get("request") or {}).get("document_id")
            workflow_id = job.get("id") or str(uuid4())
            operation = "extraction" if job.get("kind") == "extraction" else kind
            try:
                client = get_service_client()
                client.table("ai_quiz_workflows").upsert({
                    "id": workflow_id, "tenant_id": tenant, "document_id": document,
                    "kind": operation, "status": "running",
                }).execute()
            except Exception as exc:
                logger.warning("Unable to record AI cost workflow: %s", type(exc).__name__)
                return function(*args, **kwargs)
            token = _context.set({**_context.get(), "workflow_id": workflow_id})
            status, quiz_id = "failed", None
            try:
                result = function(*args, **kwargs)
                quiz_id = result.get("quiz_set_id") if isinstance(result, dict) else None
                status = "completed"
                return result
            finally:
                _context.reset(token)
                try:
                    client.table("ai_quiz_workflows").update({
                        "status": status, "quiz_set_id": quiz_id,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", workflow_id).eq("tenant_id", tenant).execute()
                except Exception as exc:
                    logger.warning("Unable to finish AI cost workflow: %s", type(exc).__name__)
        return tracked
    return decorate


@contextmanager
def ai_provider_attempt(*, was_fallback: bool) -> Iterator[None]:
    """Mark the current provider leg without losing the owning pipeline context."""
    token = _context.set({**_context.get(), "provider_fallback": was_fallback})
    try:
        yield
    finally:
        _context.reset(token)


def _integer(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _usage(provider: str, response: dict | None) -> tuple[int | None, int | None, int | None, int | None]:
    usage = (response or {}).get("usageMetadata" if provider == "gemini" else "usage") or {}
    if provider == "gemini":
        return (
            _integer(usage.get("promptTokenCount")),
            _integer(usage.get("candidatesTokenCount")),
            _integer(usage.get("cachedContentTokenCount")),
            _integer(usage.get("thoughtsTokenCount")),
        )
    completion_details = usage.get("completion_tokens_details") or {}
    return (
        _integer(usage.get("prompt_tokens")),
        _integer(usage.get("completion_tokens")),
        _integer(usage.get("prompt_cache_hit_tokens")),
        _integer(completion_details.get("reasoning_tokens")),
    )


def calculate_costs(
    *, model: str, input_tokens: int | None, output_tokens: int | None,
    cached_tokens: int | None, thinking_tokens: int | None,
    usd_to_inr_rate: float | None = None,
) -> tuple[Decimal | None, Decimal | None]:
    """Return USD/INR estimates, or null costs when the model has no published mapping."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None or input_tokens is None or output_tokens is None:
        return None, None
    input_rate, output_rate, cached_rate, thinking_in_output = pricing
    incoming = Decimal(max(0, (input_tokens or 0) - (cached_tokens or 0)))
    cached = Decimal(cached_tokens or 0)
    outgoing = Decimal(output_tokens or 0)
    thinking = Decimal(thinking_tokens or 0)
    usd = (incoming * input_rate + cached * cached_rate + outgoing * output_rate) / Decimal(1_000_000)
    if not thinking_in_output:
        # Models without a separate published thinking rate report it only for
        # observability; billing remains the provider's published output price.
        usd += Decimal(0) * thinking
    usd = usd.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    exchange_rate = usd_to_inr_rate if usd_to_inr_rate is not None else get_settings().usd_to_inr_rate
    inr = (usd * Decimal(str(exchange_rate))).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )
    return usd, inr


def _write(row: dict[str, Any]) -> None:
    try:
        get_service_client().table("api_call_logs").insert(row).execute()
    except Exception as exc:  # observability must never change user-facing behaviour
        logger.warning("Unable to persist AI API call log: %s", type(exc).__name__)


def _logging_enabled() -> bool:
    """Never let test traffic reach an external observability table."""
    return getattr(get_settings(), "app_env", "production") != "test"


def log_ai_call(
    *, provider: str, model: str, request: dict, response: dict | None,
    was_fallback: bool, started_at: float, error_message: str | None = None,
) -> None:
    """Queue cost/health metadata without persisting prompts or responses."""
    if not _logging_enabled():
        return
    input_tokens, output_tokens, cached_tokens, thinking_tokens = _usage(provider, response)
    cost_usd, cost_inr = calculate_costs(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        thinking_tokens=thinking_tokens,
    )
    context = _context.get()
    row = {
        "call_type": context["call_type"],
        "tenant_id": context["tenant_id"],
        "document_id": context["document_id"],
        "job_id": context["job_id"],
        "evaluation_job_id": context["evaluation_job_id"],
        "provider": provider,
        "model": model,
        "was_fallback": was_fallback or bool(context.get("provider_fallback")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "thinking_tokens": thinking_tokens,
        "cost_usd": str(cost_usd) if cost_usd is not None else None,
        "cost_inr": str(cost_inr) if cost_inr is not None else None,
        "latency_ms": max(0, round((time.perf_counter() - started_at) * 1000)),
        "status": "error" if error_message else "success",
        "error_message": error_message,
    }
    if context.get("workflow_id"):
        row["workflow_id"] = context["workflow_id"]
    threading.Thread(target=_write, args=(row,), daemon=True).start()
