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

from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.chunking_service import ChunkingService
from app.services.document_profile import profile_document, profile_to_summary
from app.services.extraction import extract_text
from app.services.master_blueprint_synthesizer import MasterBlueprintSynthesizer
from app.services.topic_extraction_pipeline import TopicExtractionPipeline

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_text_loader(client, document_id: str, tenant_id: str) -> str:
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
    text = extract_text(download_bytes(doc.data["storage_path"]), doc.data["file_type"])
    if not text.strip():
        raise ValueError("This document has no extractable text (scanned image PDF?).")
    return text


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
            text = self._text_loader(self._client, document_id, tenant_id)

            # 1b) PROFILE — understand the document once (subject + summary), so
            #     MAP/REDUCE can judge what is core vs. noise. Reused on resume.
            profile = (job.get("params") or {}).get("document_profile")
            if not profile:
                profile = self._profiler(text)
                self._update(
                    job_id,
                    tenant_id,
                    params={**(job.get("params") or {}), "document_profile": profile},
                )
            summary = profile_to_summary(profile)

            self._chunker.chunk_and_store(
                document_id=document_id, tenant_id=tenant_id, text=text
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
            )
            self._update(job_id, tenant_id, done_chunks=map_res["succeeded"])
            if map_res["succeeded"] == 0:
                raise RuntimeError("Topic extraction failed for every chunk.")

            # 3) REDUCE (consolidate whatever succeeded into the Master Blueprint).
            self._update(job_id, tenant_id, phase="reducing")
            blueprint = self._reducer.synthesize(
                document_id=document_id,
                tenant_id=tenant_id,
                document_title=title,
                document_summary=summary,
            )

            # 'partial' if some chunks never mapped: the blueprint is usable, but a
            # retry can still fill the gaps and upgrade the job to 'completed'.
            final_status = "completed" if map_res["failed"] == 0 else "partial"
            self._update(
                job_id,
                tenant_id,
                master_blueprint=blueprint,
                phase="ready",
                status=final_status,
            )
            return {
                "status": final_status,
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
