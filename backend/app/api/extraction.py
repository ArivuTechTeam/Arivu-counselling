"""
Quiz EXTRACTION API.

  POST /api/v1/quiz-sets/extract  — teacher uploads an existing quiz document
    (typed PDF, scanned image, or DOCX); the configured AI provider extracts
    the questions and stores them as a DRAFT quiz set (pending review) under
    the chosen subject.

Isolated in its own router so the core generator (quiz.py / generation.py) is
untouched. Accepts its own multipart upload (so it can take images, which the
shared /documents upload deliberately does not) and stores the file the same
way, then hands off to the extraction orchestrator.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.api_errors import public_error
from app.lib.config import get_settings
from app.lib.storage import delete_bytes, upload_bytes
from app.lib.supabase import get_service_client
from app.services.llm import LLMError
from app.services.quiz_extraction import extract_quiz
from app.services.rate_limit import QUIZ_EXTRACTION, enforce_ai_rate_limit

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["extraction"])
logger = logging.getLogger(__name__)

# Vision handles scans/typed PDFs; DOCX goes via text. Images allowed here even
# though the shared /documents upload only takes pdf/docx.
ALLOWED_EXT = {"pdf", "docx", "png", "jpg", "jpeg"}
MAX_MB = 20  # inline-to-Gemini limit; quiz papers are small
MAX_BYTES = MAX_MB * 1024 * 1024
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _require_teacher(profile: CurrentProfile) -> None:
    # Teacher-only by design — see CLAUDE.md.
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can extract quizzes.",
        )


def _has_expected_signature(ext: str, content: bytes) -> bool:
    """Reject renamed or malformed files before storage and model processing."""
    if ext == "pdf":
        return content[:1024].lstrip().startswith(b"%PDF-")
    if ext == "png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {"jpg", "jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if ext == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and "word/document.xml" in names
        except (OSError, zipfile.BadZipFile):
            return False
    return False


@router.post("/extract")
async def extract_quiz_endpoint(
    file: UploadFile = File(...),
    subject_id: str = Form(...),
    chapter_id: str = Form(...),
    force: bool = Form(False),
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    _require_teacher(profile)

    filename = file.filename or "upload"
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supported files: PDF, DOCX, PNG, JPG.",
        )

    content = await file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large for extraction (max {MAX_MB} MB).",
        )
    if not _has_expected_signature(ext, content):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The selected file does not appear to be a valid PDF, DOCX, "
                "PNG, or JPG."
            ),
        )

    service = get_service_client()

    # Soft duplicate guard: if this EXACT file was already uploaded in this
    # tenant, ask the teacher to confirm (409) rather than silently duplicating.
    # (Checked BEFORE storing so a declined duplicate leaves no orphan file/row.)
    content_hash = hashlib.sha256(content).hexdigest()
    if not force:
        dup = (
            service.table("documents")
            .select("original_filename, created_at")
            .eq("tenant_id", profile.tenant_id)
            .eq("uploaded_by", profile.user_id)
            .eq("content_hash", content_hash)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if dup:
            prev_name = dup[0].get("original_filename") or "a file"
            when = str(dup[0].get("created_at") or "")[:10]
            msg = f"You already uploaded this exact file (‘{prev_name}’"
            msg += f" on {when})." if when else ")."
            msg += " Extract it again anyway?"
            raise HTTPException(status_code=409, detail=msg)

    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUIZ_EXTRACTION,
        hourly_limit=get_settings().rate_limit_quiz_extraction_per_hour,
        action_label="quiz extraction",
    )

    # 1) Store the original under the tenant folder.
    object_path = f"{profile.tenant_id}/{uuid.uuid4()}.{ext}"
    upload_bytes(object_path, content, CONTENT_TYPES[ext])

    # 2) Record the document (extraction jobs reference a document_id).
    try:
        inserted = (
            service.table("documents")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "uploaded_by": profile.user_id,
                    "storage_path": object_path,
                    "original_filename": filename,
                    "file_type": ext,
                    "status": "uploaded",
                    "content_hash": content_hash,
                }
            )
            .execute()
        )
    except Exception:
        try:
            delete_bytes(object_path)
        except Exception:  # noqa: BLE001 - retain the original database error
            logger.exception(
                "Could not remove orphaned extraction upload %s", object_path
            )
        raise
    document_id = inserted.data[0]["id"]

    # 3) Extract with the configured AI providers and persist. Off the event
    #    loop because it performs blocking network and database work.
    try:
        result = await run_in_threadpool(
            extract_quiz,
            document_id=document_id,
            subject_id=subject_id,
            chapter_id=chapter_id,
            profile=profile,
        )
    except ValueError as exc:
        raise public_error(
            400,
            "The selected file or academic selection could not be used for extraction.",
            operation="prepare quiz extraction",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            502,
            "We couldn't extract this quiz right now. Please try again.",
            operation="extract quiz with AI",
            exception=exc,
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected quiz extraction failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We couldn't finish extracting this quiz. Please try again.",
        ) from exc

    return result


@router.post("/{document_id}/re-extract")
async def re_extract_quiz_endpoint(
    document_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Retry extraction on an ALREADY-uploaded document — no re-upload.

    Reuses the file already in storage and the chapter the document was filed
    under, so a teacher whose extraction failed (e.g. the AI timed out) can try
    again in one click. Because nothing is re-uploaded, the duplicate-file guard
    never triggers.
    """
    _require_teacher(profile)
    service = get_service_client()

    # Own document only, tenant-scoped (service client bypasses RLS).
    doc = (
        service.table("documents")
        .select("chapter_id")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    chapter_id = doc.data.get("chapter_id")
    if not chapter_id:
        raise HTTPException(
            status_code=400,
            detail="This document isn't filed under a chapter yet. "
            "Please extract it from the Extract tab.",
        )

    chapter = (
        service.table("chapters")
        .select("subject_id")
        .eq("id", chapter_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if chapter is None or not chapter.data:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    subject_id = chapter.data["subject_id"]

    enforce_ai_rate_limit(
        profile=profile,
        endpoint=QUIZ_EXTRACTION,
        hourly_limit=get_settings().rate_limit_quiz_extraction_per_hour,
        action_label="quiz extraction",
    )

    try:
        result = await run_in_threadpool(
            extract_quiz,
            document_id=document_id,
            subject_id=subject_id,
            chapter_id=chapter_id,
            profile=profile,
        )
    except ValueError as exc:
        raise public_error(
            400,
            "The stored document or its academic selection could not be used "
            "for extraction.",
            operation="prepare quiz re-extraction",
            exception=exc,
        ) from exc
    except LLMError as exc:
        raise public_error(
            502,
            "We couldn't extract this quiz right now. Please try again.",
            operation="re-extract quiz with AI",
            exception=exc,
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected quiz re-extraction failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We couldn't finish extracting this quiz. Please try again.",
        ) from exc

    return result
