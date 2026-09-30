"""Durable faculty work. No provider calls or daemon workers in HTTP handlers."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.supabase import get_service_client
from app.services.teacher_access import teacher_has_subject
from app.services.tenant_features import require_profile_feature


PUBLIC_COLUMNS = "id,kind,status,phase,attempts,result,error_message,created_at,updated_at"


def public_job(row: dict) -> dict:
    result = {key: row.get(key) for key in PUBLIC_COLUMNS.split(",")}
    if result["result"]:
        # Status polling should not transfer entire question banks every few seconds.
        raw_result = result["result"]
        result["result"] = {
            key: raw_result.get(key)
            for key in ("quiz_set_id", "generated_paper_id", "regenerated", "kept", "total")
            if raw_result.get(key) is not None
        }
    elif row.get("quiz_set_id"):
        result["result"] = {"quiz_set_id": row["quiz_set_id"]}
    request = row.get("request") or {}
    result["source_document_id"] = request.get("document_id")
    if request.get("generated_paper_id"):
        result["generated_paper_id"] = request["generated_paper_id"]
    return result


def validate_source(service, profile: CurrentProfile, request: dict) -> None:
    if not teacher_has_subject(service, profile, request["subject_id"]):
        raise HTTPException(404, "Subject not found.")
    document = (service.table("documents").select("id,status")
                .eq("id", request["document_id"]).eq("tenant_id", profile.tenant_id)
                .eq("uploaded_by", profile.user_id).maybe_single().execute())
    if not document or not document.data or document.data.get("status") == "archived":
        raise HTTPException(404, "Document not found.")
    if request.get("chapter_id"):
        chapter = (service.table("chapters").select("id").eq("id", request["chapter_id"])
                   .eq("subject_id", request["subject_id"]).eq("tenant_id", profile.tenant_id)
                   .maybe_single().execute())
        if not chapter or not chapter.data:
            raise HTTPException(404, "Chapter not found.")


def find_request(profile: CurrentProfile, key: str) -> dict | None:
    try:
        key = str(UUID(key))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Invalid request identifier.") from exc
    response = (get_service_client().table("faculty_jobs").select("*")
                .eq("request_key", key).eq("tenant_id", profile.tenant_id)
                .eq("created_by", profile.user_id).maybe_single().execute())
    return response.data if response else None


def enqueue(profile: CurrentProfile, key: str, kind: str, request: dict) -> dict:
    require_profile_feature(profile, "faculty_jobs", label="Background processing")
    if profile.role != "teacher":
        raise HTTPException(403, "Only teachers can create these jobs.")
    try:
        key = str(UUID(key))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Invalid request identifier.") from exc
    service = get_service_client()
    validate_source(service, profile, request)
    settings = get_settings()
    if kind == "extraction":
        limit = settings.rate_limit_quiz_extraction_per_hour
    elif kind == "regenerate_set":
        limit = settings.rate_limit_quiz_generation_per_hour
    else:
        limit = settings.rate_limit_blueprint_per_hour
    identity = dict(request)
    if kind == "extraction" and identity.get("content_hash"):
        # Concurrent upload retries may create distinct temporary document rows.
        # File bytes + academic selection define the same import intent.
        identity.pop("document_id", None)
    fingerprint = hashlib.sha256(json.dumps({"kind": kind, "request": identity}, sort_keys=True).encode()).hexdigest()
    row = service.rpc("enqueue_faculty_job", {
        "p_tenant": profile.tenant_id, "p_actor": profile.user_id, "p_key": key,
        "p_kind": kind, "p_request": request, "p_hash": fingerprint, "p_limit": limit,
    }).execute().data
    if not isinstance(row, dict):
        raise HTTPException(503, "Could not confirm the background request. Check your recent tasks before retrying.")
    if row.get("conflict"):
        raise HTTPException(409, "This request identifier belongs to different settings. Start a new request.")
    if row.get("rate_limited"):
        raise HTTPException(429, "You have reached the hourly limit. Please try again later.",
                            headers={"Retry-After": str(row.get("retry_after_seconds", 60))})
    return public_job(row)


def enqueue_generated_paper(profile: CurrentProfile, key: str, request: dict) -> dict:
    """Atomically create a generated-paper record and its leased worker job."""
    require_profile_feature(profile, "faculty_jobs", label="Background processing")
    if profile.role != "teacher":
        raise HTTPException(403, "Only teachers can generate exam papers.")
    try:
        key = str(UUID(key))
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "Invalid request identifier.") from exc
    fingerprint = hashlib.sha256(
        json.dumps({"kind": "generate_paper", "request": request}, sort_keys=True).encode()
    ).hexdigest()
    row = get_service_client().rpc("enqueue_generated_paper_job", {
        "p_id": str(uuid4()),
        "p_tenant": profile.tenant_id,
        "p_actor": profile.user_id,
        "p_key": key,
        "p_request": request,
        "p_hash": fingerprint,
        "p_limit": get_settings().rate_limit_paper_generation_per_hour,
    }).execute().data
    if not isinstance(row, dict):
        raise HTTPException(503, "Could not confirm the paper request. Check your history before retrying.")
    if row.get("conflict"):
        raise HTTPException(409, "This request identifier belongs to different settings. Start a new request.")
    if row.get("rate_limited"):
        raise HTTPException(
            429,
            "You have reached the hourly paper-generation limit. Please try again later.",
            headers={"Retry-After": str(row.get("retry_after_seconds", 60))},
        )
    return public_job(row)


def load_owned(job_id: str, profile: CurrentProfile) -> dict:
    row = (get_service_client().table("faculty_jobs").select(PUBLIC_COLUMNS)
           .eq("id", job_id).eq("tenant_id", profile.tenant_id)
           .eq("created_by", profile.user_id).maybe_single().execute())
    if not row or not row.data:
        raise HTTPException(404, "Task not found.")
    return public_job(row.data)
