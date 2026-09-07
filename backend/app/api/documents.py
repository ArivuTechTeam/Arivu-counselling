"""
Document upload + listing API (Slice 2).

Flow for POST /api/v1/documents/upload:
  1. Verify the caller is staff (students can't upload).
  2. Validate the file (type + size).
  3. Store the original bytes in the tenant's Storage folder.
  4. Record a `documents` row.
  5. Extract text; mark the row completed/failed.
  6. Return a preview of the extracted text.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.storage import upload_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

ALLOWED_EXT = {"pdf", "docx"}
MAX_MB = 150
MAX_BYTES = MAX_MB * 1024 * 1024
PREVIEW_CHARS = 5000
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
}


class DocumentOut(BaseModel):
    id: str
    original_filename: str | None
    file_type: str | None
    status: str
    created_at: str


class UploadResult(BaseModel):
    document: DocumentOut
    text_preview: str
    char_count: int
    truncated: bool


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _require_teacher(profile: CurrentProfile) -> None:
    if profile.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers can upload documents.",
        )


@router.post("/upload", response_model=UploadResult)
async def upload_document(
    file: UploadFile = File(...),
    profile: CurrentProfile = Depends(get_current_profile),
) -> UploadResult:
    _require_teacher(profile)

    filename = file.filename or "upload"
    ext = _ext_of(filename)
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF and DOCX files are supported.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {MAX_MB} MB).",
        )

    # 1) Store the original file under the tenant's folder for isolation.
    object_path = f"{profile.tenant_id}/{uuid.uuid4()}.{ext}"
    upload_bytes(object_path, content, CONTENT_TYPES[ext])

    service = get_service_client()

    # 2) Record the document. The service client bypasses RLS, so we set
    #    tenant_id and uploaded_by explicitly from the VERIFIED profile.
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
    row = inserted.data[0]
    doc_id = row["id"]

    # 3) Extract text and mark the row completed/failed. pdfplumber/python-docx are
    #    synchronous and CPU-bound, so run them off the event loop or they'd block
    #    every other request this worker is handling.
    try:
        text = await run_in_threadpool(extract_text, content, ext)
    except Exception as exc:  # noqa: BLE001 - surface any parse failure to the row
        service.table("documents").update(
            {"status": "failed", "error_message": str(exc)}
        ).eq("id", doc_id).execute()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract text from this file. It may be corrupted, "
            "password-protected, or in an unsupported format.",
        )

    service.table("documents").update({"status": "completed"}).eq(
        "id", doc_id
    ).execute()

    char_count = len(text)
    return UploadResult(
        document=DocumentOut(
            id=doc_id,
            original_filename=filename,
            file_type=ext,
            status="completed",
            created_at=str(row["created_at"]),
        ),
        text_preview=text[:PREVIEW_CHARS],
        char_count=char_count,
        truncated=char_count > PREVIEW_CHARS,
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[DocumentOut]:
    _require_teacher(profile)
    service = get_service_client()
    rows = (
        service.table("documents")
        .select("id, original_filename, file_type, status, created_at")
        .eq("tenant_id", profile.tenant_id)  # tenant isolation enforced here
        .eq("uploaded_by", profile.user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [
        DocumentOut(
            id=r["id"],
            original_filename=r.get("original_filename"),
            file_type=r.get("file_type"),
            status=r["status"],
            created_at=str(r["created_at"]),
        )
        for r in rows.data
    ]
