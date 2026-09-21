"""Run with `python -m app.services.faculty_worker` in a separate process."""
from __future__ import annotations

import logging
import signal
import threading

from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.blueprint import generate_blueprint_quiz
from app.services.faculty_jobs import validate_source
from app.services.llm import LLMError
from app.services.quiz_extraction import _extract_document_content, _prefix_pyq, _validate_import_candidates
from app.services.quiz_generator_service import QuizGeneratorService

logger = logging.getLogger(__name__)


class LeaseLost(RuntimeError):
    pass


def update_job(service, job: dict, action: str, **extra) -> bool:
    return bool(service.rpc("update_faculty_job", {
        "p_id": job["id"], "p_tenant": job["tenant_id"], "p_actor": job["created_by"],
        "p_token": job["lease_token"], "p_action": action, **extra,
    }).execute().data)


def prepare_extraction(service, job: dict, profile: CurrentProfile) -> dict:
    request = job["request"]
    document = (service.table("documents").select("storage_path,file_type")
                .eq("id", request["document_id"]).eq("tenant_id", profile.tenant_id)
                .eq("uploaded_by", profile.user_id).maybe_single().execute().data)
    chapter = (service.table("chapters").select("name").eq("id", request["chapter_id"])
               .eq("tenant_id", profile.tenant_id).eq("subject_id", request["subject_id"])
               .maybe_single().execute().data)
    if not document or not chapter:
        raise ValueError("Source or chapter unavailable")
    content = download_bytes(document["storage_path"])
    raw, provider = _extract_document_content(
        content=content,
        ext=document["file_type"],
        tenant_id=profile.tenant_id,
        document_id=request["document_id"],
        job_id=job["id"],
    )
    questions, receipt = _validate_import_candidates(raw)
    if not questions:
        raise ValueError("No usable questions found")
    confidences = [q.confidence for q in questions if q.confidence is not None]
    return {
        "title": chapter["name"], "variant_type": "mixed", "source": "extracted",
        "provider": provider, "import_summary": receipt,
        "overall_confidence": sum(confidences) / len(confidences) if confidences else None,
        "questions": [{**q.model_dump(), "explanation": _prefix_pyq(q.explanation, q.is_pyq, q.year),
                       "verification_status": "needs_teacher_review", "verification_warnings": q.verification_warnings}
                      for q in questions],
    }


def process_job(service, job: dict) -> dict:
    profile = CurrentProfile(user_id=job["created_by"], tenant_id=job["tenant_id"], role="teacher")
    request = job["request"]
    # Authorization can change while a request waits. Recheck before provider
    # access; SQL also checks again before committing the result.
    owner = (service.table("profiles").select("role,tenant_id")
             .eq("id", profile.user_id).eq("tenant_id", profile.tenant_id).maybe_single().execute().data)
    tenant = (service.table("tenants").select("is_active").eq("id", profile.tenant_id)
              .maybe_single().execute().data)
    if not owner or owner.get("role") != "teacher" or not tenant or not tenant.get("is_active"):
        raise ValueError("Teacher or institution is no longer active")
    validate_source(service, profile, request)

    def commit(payload: dict) -> dict:
        if not update_job(service, job, "checkpoint", p_payload=payload):
            raise LeaseLost("Worker no longer owns this job")
        return service.rpc("finish_faculty_job", {"p_id": job["id"], "p_token": job["lease_token"]}).execute().data

    if job.get("checkpoint"):
        # A crash after preparation must not consume another model call.
        return service.rpc("finish_faculty_job", {"p_id": job["id"], "p_token": job["lease_token"]}).execute().data
    if job["kind"] == "extraction":
        return commit(prepare_extraction(service, job, profile))
    arguments = {key: request[key] for key in (
        "subject_id", "chapter_name", "selected_topics", "total_questions",
        "question_types", "type_counts", "cognitive_level", "difficulty",
    )}
    arguments.update(profile=profile, persist_result=commit)
    if job["kind"] == "analysis_quiz":
        return QuizGeneratorService(service).generate_from_job(job_id=request["analysis_job_id"], **arguments)
    return generate_blueprint_quiz(document_id=request["document_id"], **arguments)


def run_one(service=None, *, heartbeat_seconds: float = 20) -> bool:
    service = service or get_service_client()
    job = service.rpc("claim_faculty_job", {}).execute().data
    if not job:
        return False
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(heartbeat_seconds):
            try:
                if not update_job(service, job, "heartbeat"):
                    return
            except Exception as exc:
                # A lost connection may be temporary; the DB lease remains the
                # authority. A late worker can never commit after its expiry.
                logger.warning("Job heartbeat failed (%s)", type(exc).__name__)

    thread = threading.Thread(target=heartbeat, daemon=True, name="faculty-job-heartbeat")
    thread.start()
    try:
        process_job(service, job)
    except LeaseLost:
        logger.info("Faculty job lease no longer held: %s", job["id"])
    except Exception as exc:
        logger.warning("Faculty job failed: %s (%s)", job["id"], type(exc).__name__)
        # No raw provider/source details in logs or public status. Recoverable
        # failures are bounded to three attempts; invalid inputs fail immediately.
        retryable = isinstance(exc, LLMError) or not isinstance(exc, (ValueError, HTTPException))
        try:
            update_job(service, job, "fail", p_retryable=retryable)
        except Exception:
            logger.warning("Could not record job failure; lease recovery will resume it.")
    finally:
        done.set()
        thread.join(timeout=2)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    if not settings.faculty_jobs_enabled:
        raise SystemExit("Set FACULTY_JOBS_ENABLED=true after applying the faculty-job migration.")
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    # Each process handles one provider job at a time. Database claims enforce
    # shared caps (four globally, two per tenant) across all worker processes.
    while not stop.is_set():
        try:
            worked = run_one()
        except Exception as exc:
            logger.warning("Worker queue unavailable (%s)", type(exc).__name__)
            worked = False
        if not worked:
            stop.wait(settings.faculty_jobs_poll_seconds)


if __name__ == "__main__":
    main()
