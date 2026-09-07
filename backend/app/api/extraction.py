"""
Quiz EXTRACTION API.

  POST /api/v1/quiz-sets/extract  — teacher uploads an existing quiz document
    (typed PDF, scanned image, or DOCX); Gemini extracts the questions and
    stores them as a DRAFT quiz set (pending review) under the chosen subject.

Isolated in its own router so the core generator (quiz.py / generation.py) is
untouched. Accepts its own multipart upload (so it can take images, which the
shared /documents upload deliberately does not) and stores the file the same
way, then hands off to the extraction orchestrator.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.storage import upload_bytes
from app.lib.supabase import get_service_client
from app.services.llm import LLMError
from app.services.quiz_extraction import extract_quiz

router = APIRouter(prefix="/api/v1/quiz-sets", tags=["extraction"])

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
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can extract quizzes.",
        )


@router.post("/extract")
async def extract_quiz_endpoint(
    file: UploadFile = File(...),
    subject_id: str = Form(...),
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

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large for extraction (max {MAX_MB} MB).",
        )

    # 1) Store the original under the tenant folder.
    object_path = f"{profile.tenant_id}/{uuid.uuid4()}.{ext}"
    upload_bytes(object_path, content, CONTENT_TYPES[ext])

    # 2) Record the document (extraction jobs reference a document_id).
    service = get_service_client()
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
            }
        )
        .execute()
    )
    document_id = inserted.data[0]["id"]

    # 3) Extract (Gemini vision/text + persist). Off the event loop — it does
    #    blocking network + DB work.
    try:
        result = await run_in_threadpool(
            extract_quiz,
            document_id=document_id,
            subject_id=subject_id,
            profile=profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LLMError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not extract the quiz: {exc}",
        )

    return result
