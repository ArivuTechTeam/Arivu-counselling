"""
Large-document generation-job orchestration (analysis phase).

Ties the pieces together for a >trigger document, resumably:

    chunk_and_store  ->  MAP (TopicExtractionPipeline)  ->  REDUCE (blueprint)

and records progress on the `quiz_generation_jobs` row (status + phase +
done/total chunks + the Master Blueprint) so the teacher's screen can poll it.

Resumability is free: every step is idempotent. `chunk_and_store` skips chunks
already stored, MAP skips chunks already succeeded, and REDUCE simply re-runs on
whatever succeeded. So re-invoking `run()` after a crash/restart continues where
it stopped rather than repeating work. A failed or stuck job is retried by
calling `launch_job(job_id)` again.

Runs in a daemon thread (no Celery/Redis) — matching the rest of the backend.
The final quiz itself is NOT made here; that's the teacher-driven generation
step (QuizGeneratorService) after they pick topics from the blueprint.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.chunking_service import ChunkingService
from app.services.document_profile import profile_document, profile_to_summary
from app.services.extraction import ExtractedText, extract_text_with_pages, require_readable_generation_pages
from app.services.master_blueprint_synthesizer import MasterBlueprintSynthesizer
from app.services.topic_extraction_pipeline import TopicExtractionPipeline
from app.services.rate_limit import TOPIC_EXTRACTION, enforce_ai_rate_limit

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_text_loader(client, document_id: str, tenant_id: str) -> ExtractedText:
    """Fetch a stored document (tenant-scoped) and extract its text."""
    doc = (
        client.table("documents")
        .select("storage_path, file_type")
        .eq("id", document_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    extracted = extract_text_with_pages(
        download_bytes(doc.data["storage_path"]), doc.data["file_type"]
    )
    if not extracted.text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    require_readable_generation_pages(extracted)
    return extracted


class GenerationJobRunner:
    """Executes the analysis pipeline for one job. Collaborators are injectable
    so the orchestration can be unit-tested without DB/LLM/storage."""

    def __init__(
        self,
        service=None,
        *,
        chunker=None,
        mapper=None,
        reducer=None,
        text_loader=None,
        profiler=None,
    ) -> None:
        self._service = service
        self._chunker = chunker or ChunkingService(service)
        self._mapper = mapper or TopicExtractionPipeline(service)
        self._reducer = reducer or MasterBlueprintSynthesizer(service)
        self._text_loader = text_loader or _default_text_loader
        self._profiler = profiler or profile_document

    @property
    def _client(self):
        return self._service or get_service_client()

    def _load_job(self, job_id: str) -> dict | None:
        res = (
            self._client.table("quiz_generation_jobs")
            .select("*")
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
        return res.data if res and res.data else None

    def _update(self, job_id: str, tenant_id: str, **fields) -> None:
        fields["updated_at"] = _now()
        (
            self._client.table("quiz_generation_jobs")
            .update(fields)
            .eq("id", job_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )

    def _count_chunks(self, document_id: str, tenant_id: str) -> int:
        rows = (
            self._client.table("document_chunks")
            .select("id")
            .eq("document_id", document_id)
            .eq("tenant_id", tenant_id)
            .execute()
            .data
            or []
        )
        return len(rows)

    def run(self, *, job_id: str) -> dict:
        job = self._load_job(job_id)
        if not job:
            logger.warning("Generation job %s not found; skipping.", job_id)
            return {"status": "missing"}

        tenant_id = job["tenant_id"]
        document_id = job["document_id"]
        title = (job.get("chapter_name") or "").strip()

        try:
            # 1) CHUNK (idempotent — resumes without re-storing).
            self._update(
                job_id, tenant_id, status="running", phase="chunking", error_message=None
            )
            loaded = self._text_loader(self._client, document_id, tenant_id)
            if isinstance(loaded, ExtractedText):
                text = loaded.text
                page_spans = loaded.page_spans
            else:  # backwards-compatible injectable used by focused unit tests
                text = str(loaded)
                page_spans = ()

            actor_profile = CurrentProfile(
                user_id=job["created_by"], tenant_id=tenant_id, role="teacher"
            )

            # 1b) PROFILE — understand the document once (subject + summary), so
            #     MAP/REDUCE can judge what is core vs. noise. Reused on resume.
            params = job.get("params") or {}
            document_profile = params.get("document_profile") or {}
            if not params.get("document_profile_attempted"):
                if not params.get("profile_rate_limit_reserved"):
                    enforce_ai_rate_limit(
                        profile=actor_profile,
                        endpoint=TOPIC_EXTRACTION,
                        hourly_limit=get_settings().rate_limit_topic_extraction_per_hour,
                        action_label="large-document analysis",
                    )
                document_profile = self._profiler(text)
                self._update(
                    job_id,
                    tenant_id,
                    params={
                        **params,
                        "document_profile": document_profile,
                        "document_profile_attempted": True,
                    },
                )
            summary = profile_to_summary(document_profile)

            self._chunker.chunk_and_store(
                document_id=document_id,
                tenant_id=tenant_id,
                text=text,
                page_spans=page_spans,
            )
            total = self._count_chunks(document_id, tenant_id)
            self._update(job_id, tenant_id, total_chunks=total)

            # 2) MAP (idempotent — only queued/failed chunks are re-mapped).
            self._update(job_id, tenant_id, phase="mapping")
            map_res = self._mapper.run(
                document_id=document_id,
                tenant_id=tenant_id,
                document_title=title,
                document_summary=summary,
                profile=actor_profile,
            )
            self._update(job_id, tenant_id, done_chunks=map_res["succeeded"])
            if map_res["succeeded"] == 0:
                raise RuntimeError("Topic extraction failed for every chunk.")
            if map_res["failed"]:
                message = (
                    f"{map_res['failed']} of {map_res['total']} document sections "
                    "could not be processed. Retry to continue saved sections."
                )
                self._update(
                    job_id,
                    tenant_id,
                    status="partial",
                    phase="mapping",
                    master_blueprint=None,
                    error_message=message,
                )
                return {
                    "status": "partial",
                    "total": map_res["total"],
                    "succeeded": map_res["succeeded"],
                    "failed": map_res["failed"],
                }

            # 3) REDUCE only after every chunk succeeded. A partial blueprint can
            # silently omit late-document content, so the teacher must retry first.
            self._update(job_id, tenant_id, phase="reducing")
            blueprint = self._reducer.synthesize(
                document_id=document_id,
                tenant_id=tenant_id,
                document_title=title,
                document_summary=summary,
                profile=actor_profile,
            )

            self._update(
                job_id,
                tenant_id,
                master_blueprint=blueprint,
                phase="ready",
                status="completed",
            )
            return {
                "status": "completed",
                "total": map_res["total"],
                "succeeded": map_res["succeeded"],
                "failed": map_res["failed"],
            }
        except Exception as exc:  # noqa: BLE001 - record failure, allow retry
            logger.warning("Generation job %s failed: %s", job_id, type(exc).__name__)
            self._update(
                job_id, tenant_id, status="failed", error_message=str(exc)[:500]
            )
            raise


# --- creation + background launch -------------------------------------------

def create_generation_job(
    *,
    document_id: str,
    tenant_id: str,
    created_by: str,
    subject_id: str | None = None,
    chapter_name: str | None = None,
    params: dict | None = None,
    launch: bool = True,
) -> str:
    """Insert a queued job row and (by default) start it in the background."""
    client = get_service_client()
    row = (
        client.table("quiz_generation_jobs")
        .insert(
            {
                "tenant_id": tenant_id,
                "created_by": created_by,
                "document_id": document_id,
                "subject_id": subject_id,
                "chapter_name": chapter_name,
                "params": params or {},
                "status": "queued",
                "phase": "queued",
            }
        )
        .execute()
    )
    job_id = row.data[0]["id"]
    if launch:
        launch_job(job_id)
    return job_id


def _safe_run(job_id: str) -> None:
    try:
        GenerationJobRunner().run(job_id=job_id)
    except Exception:  # noqa: BLE001 - run() already recorded the failure
        logger.warning("Background generation job %s ended in error.", job_id)


def launch_job(job_id: str) -> None:
    """Run (or resume/retry) a job on a daemon thread."""
    threading.Thread(
        target=_safe_run, args=(job_id,), daemon=True, name=f"genjob-{job_id[:8]}"
    ).start()
