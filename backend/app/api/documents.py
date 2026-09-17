"""
Document upload + listing API (Slice 2).

Flow for POST /api/v1/documents/upload:
  1. Verify the caller is a teacher.
  2. Validate the file (type + size).
  3. Store the original bytes in the tenant's Storage folder.
  4. Record a `documents` row.
  5. Extract text; mark the row completed/failed.
  6. Return a preview of the extracted text.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.lib.auth import CurrentProfile, get_current_profile
from app.lib.storage import download_bytes, signed_url, upload_bytes
from app.lib.supabase import get_service_client
from app.lib.supabase_queries import select_all, select_all_in
from app.services.extraction import MIN_READABLE_PDF_TEXT_CHARS, extract_text
from app.services.teacher_access import teacher_has_subject

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_EXT = {"pdf", "docx"}
MAX_MB = 30
MAX_BYTES = MAX_MB * 1024 * 1024
PREVIEW_CHARS = 5000
# A "view" link for a private document is short-lived to limit leakage.
SIGNED_URL_TTL_SECONDS = 300  # 5 minutes
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


class DocumentLogItem(BaseModel):
    """One row in the teacher's Document Log — a readable record of an upload
    plus the subject/chapter it was filed under (when known) and the status of
    the quiz produced from it."""

    id: str
    original_filename: str | None
    file_type: str | None
    status: str
    created_at: str
    subject_name: str | None = None
    chapter_name: str | None = None
    # What happened to this document. quiz_status is one of:
    #   "published"  - a quiz from this doc is live to students
    #   "draft"      - a quiz exists, awaiting review (not published yet)
    #   "extracting" - an extraction is running right now
    #   "failed"     - the last extraction (or upload) failed; safe to retry
    #   "none"       - nothing has been generated/extracted yet
    quiz_status: str = "none"


class DocumentFileUrl(BaseModel):
    """A short-lived link to open/download the original uploaded file."""

    url: str
    original_filename: str | None
    file_type: str | None
    expires_in: int


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _require_teacher(profile: CurrentProfile) -> None:
    # Teacher-only by design — see .claude/CLAUDE.md and the technical document.
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

    # Read at most one byte beyond the configured ceiling. This rejects an
    # oversized upload without first buffering its entire body in memory.
    content = await file.read(MAX_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File too large (max {MAX_MB} MB).",
        )

    # 1) Store the original file under the tenant's folder for isolation.
    object_path = f"{profile.tenant_id}/{uuid.uuid4()}.{ext}"
    upload_bytes(object_path, content, CONTENT_TYPES[ext])

    service = get_service_client()

    # 2) Record the document. The service client bypasses RLS, so we set
    #    tenant_id and uploaded_by explicitly from the VERIFIED profile.
    #    content_hash lets a later "same subject + chapter" re-upload be flagged
    #    (see /check-duplicate) — same SHA-256 the extraction path already stores.
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
                "content_hash": hashlib.sha256(content).hexdigest(),
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
        logger.warning("Document extraction failed (%s)", type(exc).__name__)
        service.table("documents").update(
            {"status": "failed", "error_message": "Document extraction failed."}
        ).eq("id", doc_id).eq("tenant_id", profile.tenant_id).eq(
            "uploaded_by", profile.user_id
        ).execute()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not extract text from this file. It may be corrupted, "
            "password-protected, or in an unsupported format.",
        )

    if ext == "pdf" and len(text.strip()) < MIN_READABLE_PDF_TEXT_CHARS:
        message = (
            "This looks like a scanned document with no extractable text — "
            "please use a text-based PDF, or use the Extract Quiz feature if "
            "this is a scanned question paper."
        )
        service.table("documents").update(
            {"status": "failed", "error_message": message}
        ).eq("id", doc_id).eq("tenant_id", profile.tenant_id).eq(
            "uploaded_by", profile.user_id
        ).execute()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=message,
        )

    service.table("documents").update({"status": "completed"}).eq(
        "id", doc_id
    ).eq("tenant_id", profile.tenant_id).eq(
        "uploaded_by", profile.user_id
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


class DuplicateCheckRequest(BaseModel):
    document_id: str
    subject_id: str
    chapter_name: str


class DuplicateCheckResult(BaseModel):
    duplicate: bool
    previous_filename: str | None = None
    previous_uploaded_at: str | None = None


def _find_chapter(
    service, tenant_id: str, subject_id: str, name: str
) -> str | None:
    """Return an existing chapter without mutating data during an advisory check."""
    rows = (
        service.table("chapters")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("subject_id", subject_id)
        .eq("name", name)
        .limit(1)
        .execute()
        .data
        or []
    )
    if rows:
        return rows[0]["id"]
    return None


@router.post("/check-duplicate", response_model=DuplicateCheckResult)
def check_duplicate(
    body: DuplicateCheckRequest,
    profile: CurrentProfile = Depends(get_current_profile),
) -> DuplicateCheckResult:
    """Non-blocking warning: has the SAME file already been filed under this SAME
    subject + chapter?

    Called when the teacher clicks "Extract topics" (subject + chapter + document
    are all chosen). This never blocks or creates application records — the caller
    proceeds regardless; it only surfaces a warning the teacher can act on.
    """
    _require_teacher(profile)
    service = get_service_client()

    # Authorise: the teacher must own the target subject (same rule as generation).
    if not teacher_has_subject(service, profile, body.subject_id):
        raise HTTPException(status_code=404, detail="Subject not found.")

    chapter_name = body.chapter_name.strip()
    if not chapter_name:
        raise HTTPException(status_code=400, detail="Chapter is required.")

    # Fetch the current document, scoped to the caller.
    doc = (
        service.table("documents")
        .select("id, storage_path, content_hash, chapter_id")
        .eq("id", body.document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc_row = doc.data

    # Ensure the content hash exists (backfill documents uploaded before this
    # feature). Hashing is best-effort: never block extraction if storage read
    # fails.
    content_hash = doc_row.get("content_hash")
    if not content_hash:
        try:
            content_hash = hashlib.sha256(
                download_bytes(doc_row["storage_path"])
            ).hexdigest()
            service.table("documents").update({"content_hash": content_hash}).eq(
                "id", body.document_id
            ).eq("tenant_id", profile.tenant_id).eq(
                "uploaded_by", profile.user_id
            ).execute()
        except Exception:  # noqa: BLE001 - best-effort; a missing hash just skips the check
            return DuplicateCheckResult(duplicate=False)

    # A chapter with no successfully generated quiz cannot have a duplicate quiz.
    # Keep this advisory read free of side effects; generation files the document.
    chapter_id = _find_chapter(
        service, profile.tenant_id, body.subject_id, chapter_name
    )
    if chapter_id is None:
        return DuplicateCheckResult(duplicate=False)

    # Another same-content document already filed under this exact chapter is a
    # genuine same-subject + same-chapter re-upload.
    others = (
        service.table("documents")
        .select("original_filename, created_at")
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .eq("content_hash", content_hash)
        .eq("chapter_id", chapter_id)
        .neq("id", body.document_id)
        .neq("status", "archived")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )

    if others:
        prev = others[0]
        return DuplicateCheckResult(
            duplicate=True,
            previous_filename=prev.get("original_filename"),
            previous_uploaded_at=str(prev.get("created_at") or "")[:10] or None,
        )
    return DuplicateCheckResult(duplicate=False)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[DocumentOut]:
    _require_teacher(profile)
    service = get_service_client()
    rows = select_all(
        service,
        "documents",
        "id, original_filename, file_type, status, created_at",
        configure=lambda query: query.eq(
            "tenant_id", profile.tenant_id
        ).eq("uploaded_by", profile.user_id),
        order_column="created_at",
        order_desc=True,
    )
    return [
        DocumentOut(
            id=r["id"],
            original_filename=r.get("original_filename"),
            file_type=r.get("file_type"),
            status=r["status"],
            created_at=str(r["created_at"]),
        )
        for r in rows
        if r.get("status") != "archived"
    ]


@router.get("/log", response_model=list[DocumentLogItem])
def document_log(
    profile: CurrentProfile = Depends(get_current_profile),
) -> list[DocumentLogItem]:
    """The teacher's Document Log: their own uploads, newest first, with the
    subject/chapter each was filed under when that is recorded."""
    _require_teacher(profile)
    service = get_service_client()

    # Own uploads only, tenant-scoped. Both filters are required — the service
    # client bypasses RLS, so isolation lives here.
    docs = select_all(
        service,
        "documents",
        "id, original_filename, file_type, status, created_at, chapter_id",
        configure=lambda query: query.eq("tenant_id", profile.tenant_id).eq(
            "uploaded_by", profile.user_id
        ),
        order_column="created_at",
        order_desc=True,
    )
    docs = [doc for doc in docs if doc.get("status") != "archived"]
    if not docs:
        return []

    # Resolve subject + chapter names for docs that carry a chapter, in bulk
    # (no per-row query). Every lookup stays tenant-scoped.
    chapter_ids = list({d["chapter_id"] for d in docs if d.get("chapter_id")})
    chapter_name: dict[str, str] = {}
    chapter_to_subject: dict[str, str] = {}
    subject_name: dict[str, str] = {}
    if chapter_ids:
        chapters = select_all_in(
            service,
            "chapters",
            "id, name, subject_id",
            in_column="id",
            values=chapter_ids,
            configure=lambda query: query.eq("tenant_id", profile.tenant_id),
        )
        chapter_name = {c["id"]: c["name"] for c in chapters}
        chapter_to_subject = {
            c["id"]: c["subject_id"] for c in chapters if c.get("subject_id")
        }
        subject_ids = list(set(chapter_to_subject.values()))
        if subject_ids:
            subjects = select_all_in(
                service,
                "subjects",
                "id, name",
                in_column="id",
                values=subject_ids,
                configure=lambda query: query.eq("tenant_id", profile.tenant_id),
            )
            subject_name = {s["id"]: s["name"] for s in subjects}

    doc_ids = [d["id"] for d in docs]

    # Quizzes produced from these documents (migration-23 links quiz_sets back to
    # their source). Tenant-scoped. Quizzes made before that link existed carry a
    # NULL document_id and simply don't match.
    quiz_by_doc: dict[str, set[str]] = {}
    for q in select_all_in(
        service,
        "quiz_sets",
        "id, document_id, status",
        in_column="document_id",
        values=doc_ids,
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
    ):
        did = q.get("document_id")
        if did:
            quiz_by_doc.setdefault(did, set()).add(q.get("status") or "draft")

    # Latest extraction job per document, so a running/failed attempt is visible
    # even when it produced no quiz (rows are newest-first; keep the first seen).
    latest_job: dict[str, str] = {}
    for j in select_all_in(
        service,
        "ai_extraction_jobs",
        "id, document_id, status, created_at",
        in_column="document_id",
        values=doc_ids,
        configure=lambda query: query.eq("tenant_id", profile.tenant_id),
        order_column="created_at",
        order_desc=True,
    ):
        did = j.get("document_id")
        if did and did not in latest_job:
            latest_job[did] = j.get("status") or ""

    def _quiz_status(doc_id: str, doc_status: str) -> str:
        quizzes = quiz_by_doc.get(doc_id, set())
        if "published" in quizzes:
            return "published"
        if "draft" in quizzes:
            return "draft"
        if latest_job.get(doc_id) == "running":
            return "extracting"
        if latest_job.get(doc_id) == "failed" or doc_status == "failed":
            return "failed"
        return "none"

    items: list[DocumentLogItem] = []
    for d in docs:
        cid = d.get("chapter_id")
        chap = chapter_name.get(cid) if cid else None
        sub = subject_name.get(chapter_to_subject.get(cid, "")) if cid else None
        items.append(
            DocumentLogItem(
                id=d["id"],
                original_filename=d.get("original_filename"),
                file_type=d.get("file_type"),
                status=d["status"],
                created_at=str(d["created_at"]),
                subject_name=sub,
                chapter_name=chap,
                quiz_status=_quiz_status(d["id"], d["status"]),
            )
        )
    return items


@router.post("/{document_id}/archive")
def archive_document(
    document_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> dict:
    """Hide an old upload without deleting storage or dependent quiz history."""
    _require_teacher(profile)
    service = get_service_client()
    updated = (
        service.table("documents")
        .update({"status": "archived"})
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"id": document_id, "status": "archived"}


@router.get("/{document_id}/file-url", response_model=DocumentFileUrl)
def document_file_url(
    document_id: str,
    profile: CurrentProfile = Depends(get_current_profile),
) -> DocumentFileUrl:
    """Return a short-lived signed URL to open the teacher's own uploaded file.

    The document is looked up filtered by BOTH tenant_id and uploaded_by, so a
    teacher can never obtain a link for another tenant's (or another teacher's)
    document. The raw storage path is never returned.
    """
    _require_teacher(profile)
    service = get_service_client()

    doc = (
        service.table("documents")
        .select("storage_path, original_filename, file_type")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    try:
        url = signed_url(doc.data["storage_path"], SIGNED_URL_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create a view link for this document. Please try again.",
        )

    return DocumentFileUrl(
        url=url,
        original_filename=doc.data.get("original_filename"),
        file_type=doc.data.get("file_type"),
        expires_in=SIGNED_URL_TTL_SECONDS,
    )
