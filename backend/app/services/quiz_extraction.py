"""
Quiz EXTRACTION orchestration.

Reads an existing quiz document a teacher uploaded (typed PDF, scanned image, or
DOCX) and pulls the questions out with the configured AI providers, then stores
them as a DRAFT quiz set whose questions are `pending_review` — so they flow
through the same teacher review -> publish path as generated quizzes. The
teacher review gate is the accuracy guarantee: students only ever see approved
questions.

Deliberately separate from generation.py so the core generator is untouched.
Routing is by document nature, not just extension — only scans need vision:
  Typed PDF / DOCX (has a text layer) -> extract text -> Gemini text + DeepSeek
  Scanned PDF / image (no text layer) -> Gemini vision (bytes inline, no OCR)

Raises ValueError for caller/input problems and LLMError for model problems; the
API layer maps those to HTTP status codes.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import extract_text
from app.services.extraction_prompts import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER_FILE,
    build_extraction_user_text,
)
from app.services.generation import GeneratedQuestion
from app.services.llm import LLMError
from app.services.llm.structured import (
    complete_json_with_fallback,
    gemini_json_multimodal,
)
from app.services.teacher_access import teacher_has_subject

logger = logging.getLogger(__name__)

# Which uploads the extractor accepts, and how to hand each to Gemini.
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
_VISION_EXT = {"pdf": "application/pdf", **_IMAGE_MIME}  # accepted image/pdf types
_TEXT_EXT = {"docx"}  # always extracted to text first

# A PDF with at least this much extractable text is treated as a TYPED (digital)
# document and parsed via the cheap text path. Below it, the PDF is effectively a
# scanned image and must go through Gemini vision. A real typed quiz page has
# hundreds of characters; a scanned page yields ~0 from pdfplumber.
_MIN_PDF_TEXT_CHARS = 200


class ExtractedQuestion(GeneratedQuestion):
    """A generated-question shape plus extraction-only metadata."""

    confidence: float | None = Field(default=None, ge=0, le=1)
    is_pyq: bool = False
    year: str | None = None


class ExtractedQuiz(BaseModel):
    questions: list[ExtractedQuestion]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefix_pyq(explanation: str | None, is_pyq: bool, year: str | None) -> str | None:
    """v1: carry PYQ/year in the explanation text (no dedicated columns yet)."""
    if not is_pyq:
        return explanation
    tag = f"[PYQ {year}]" if year else "[PYQ]"
    return f"{tag} {explanation}".strip() if explanation else tag


def _vision_extract(mime_type: str, content: bytes) -> tuple[dict, str]:
    """Read a scanned page/image with Gemini vision (the only path that can)."""
    raw = gemini_json_multimodal(
        EXTRACTION_SYSTEM,
        EXTRACTION_USER_FILE,
        files=[(mime_type, content)],
    )
    return raw, "gemini-vision"


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into <= max_chars chunks at paragraph boundaries, so we don't
    cut a question in half. A single paragraph larger than max_chars is
    hard-split as a last resort."""
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)

    # Break any oversized single paragraph down to the char budget.
    bounded: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            bounded.append(chunk)
        else:
            for i in range(0, len(chunk), max_chars):
                bounded.append(chunk[i : i + max_chars])
    return bounded


def _merge_questions(results: list[dict]) -> list[dict]:
    """Flatten questions from every chunk and drop duplicates (same question
    text), which can appear if a question straddles a chunk boundary."""
    seen: set[str] = set()
    merged: list[dict] = []
    for result in results:
        for q in result.get("questions") or []:
            key = " ".join(str(q.get("question_text", "")).lower().split())
            if key and key not in seen:
                seen.add(key)
                merged.append(q)
    return merged


def _extract_text_chunk(chunk: str) -> tuple[dict, str]:
    """Extract one text chunk, retrying once on a transient model error so a
    single blip doesn't fail the whole (multi-chunk) document."""
    last_error: LLMError | None = None
    for _ in range(2):
        try:
            return complete_json_with_fallback(
                EXTRACTION_SYSTEM, build_extraction_user_text(chunk)
            )
        except LLMError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _text_extract(text: str) -> tuple[dict, str]:
    """Parse already-extracted document text with the cheap text LLM (Gemini +
    DeepSeek fallback) — no vision, far fewer tokens, and it has a real fallback.

    Small documents go in one call. Large ones (120-150+ pages) are split into
    bounded chunks extracted in parallel, then merged + de-duplicated — so no
    single call has a huge, slow, timeout-prone output.
    """
    text = text.strip()
    if not text:
        raise ValueError("This document has no readable text.")

    settings = get_settings()
    chunk_chars = settings.extraction_text_chunk_chars
    if len(text) <= chunk_chars:
        return complete_json_with_fallback(
            EXTRACTION_SYSTEM, build_extraction_user_text(text)
        )

    chunks = _chunk_text(text, chunk_chars)
    workers = max(1, min(settings.extraction_chunk_concurrency, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map preserves input order; any chunk that still fails after its retry
        # raises here, which cleanly aborts the whole job (no partial quiz).
        pairs = list(pool.map(_extract_text_chunk, chunks))

    merged = _merge_questions([raw for raw, _ in pairs])
    provider = pairs[0][1] if pairs else "text"
    return {"questions": merged}, f"{provider} (chunked x{len(chunks)})"


def _extract_document_content(
    *, content: bytes, ext: str
) -> tuple[dict, str]:
    """Route by document nature, then extract model JSON + the provider used.

    Only SCANNED pages need Gemini vision. Typed PDFs and DOCX already carry a
    text layer, so we read the text for free (pdfplumber / python-docx) and parse
    it on the cheap, fallback-backed text path — much faster and no vision
    timeout. Images always go to vision (nothing else can read them).
    """
    ext = ext.lower()

    # Images: vision is the only option.
    if ext in _IMAGE_MIME:
        return _vision_extract(_IMAGE_MIME[ext], content)

    # DOCX: always has a text layer.
    if ext == "docx":
        return _text_extract(extract_text(content, "docx"))

    # PDF: prefer the text path when it's a typed document; fall back to vision
    # when there's little/no extractable text (a scanned image PDF) or the text
    # layer can't be read at all.
    if ext == "pdf":
        try:
            text = extract_text(content, "pdf")
        except Exception:  # noqa: BLE001 - unreadable text layer -> treat as scanned
            text = ""
        if len(text.strip()) >= _MIN_PDF_TEXT_CHARS:
            return _text_extract(text)
        return _vision_extract("application/pdf", content)

    raise ValueError(f"Unsupported file type for extraction: {ext or 'unknown'}")


def extract_quiz(
    *,
    document_id: str,
    subject_id: str,
    chapter_id: str,
    profile: CurrentProfile,
) -> dict:
    service = get_service_client()

    # 0) Authorise: the teacher must own the target subject (explicit assignment
    #    is authoritative — same rule the generator enforces).
    if not teacher_has_subject(service, profile, subject_id):
        raise ValueError("Subject not found.")

    # 0b) The chapter must exist AND belong to this subject + tenant, so every
    #     extracted question is filed under the correct Subject -> Chapter.
    chapter = (
        service.table("chapters")
        .select("id, name")
        .eq("id", chapter_id)
        .eq("subject_id", subject_id)
        .eq("tenant_id", profile.tenant_id)
        .maybe_single()
        .execute()
    )
    if chapter is None or not chapter.data:
        raise ValueError("Chapter not found for this subject.")
    chapter_name = chapter.data["name"]

    # 1) Fetch the uploaded document, scoped to the caller.
    doc = (
        service.table("documents")
        .select("storage_path,file_type")
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .maybe_single()
        .execute()
    )
    if doc is None or not doc.data:
        raise ValueError("Document not found.")
    doc_row = doc.data
    ext = (doc_row.get("file_type") or "").lower()
    if ext not in _VISION_EXT and ext not in _TEXT_EXT:
        raise ValueError(f"Unsupported file type for extraction: {ext or 'unknown'}")

    # File the document under this chapter now — before the AI call — so that if
    # extraction fails (e.g. the model times out) the teacher can retry it from
    # the Document Log with no re-upload and no need to re-pick the chapter.
    (
        service.table("documents")
        .update({"chapter_id": chapter_id})
        .eq("id", document_id)
        .eq("tenant_id", profile.tenant_id)
        .eq("uploaded_by", profile.user_id)
        .execute()
    )

    settings = get_settings()

    # 2) Open an extraction job (audit + confidence trail).
    job = (
        service.table("ai_extraction_jobs")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "document_id": document_id,
                "status": "running",
                "model_used": settings.gemini_model,
            }
        )
        .execute()
    )
    job_id = job.data[0]["id"]

    quiz_set_id: str | None = None
    created_question_ids: list[str] = []
    try:
        # 3) Read PDF/images with Gemini vision; DOCX text has provider fallback.
        content = download_bytes(doc_row["storage_path"])
        raw, provider = _extract_document_content(content=content, ext=ext)

        # 4) Validate per-question; skip malformed ones (teacher reviews the rest).
        questions: list[ExtractedQuestion] = []
        skipped = 0
        for rq in raw.get("questions") or []:
            try:
                q = ExtractedQuestion.model_validate(rq)
                q.check_shape()
                questions.append(q)
            except (ValidationError, ValueError):
                skipped += 1
        if not questions:
            raise LLMError("No valid questions could be extracted from this document.")

        confidences = [q.confidence for q in questions if q.confidence is not None]
        overall_confidence = (
            round(sum(confidences) / len(confidences), 3) if confidences else None
        )

        # 5) Persist: quiz_set -> variant -> questions (pending review) -> links.
        quiz_set = (
            service.table("quiz_sets")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "chapter_id": chapter_id,
                    "subject_id": subject_id,
                    "document_id": document_id,  # link back to the source upload
                    "title": chapter_name,
                    "status": "draft",
                    "created_by": profile.user_id,
                }
            )
            .execute()
        )
        quiz_set_id = quiz_set.data[0]["id"]

        total_marks = sum(q.marks for q in questions)
        variant = (
            service.table("quiz_variants")
            .insert(
                {
                    "tenant_id": profile.tenant_id,
                    "quiz_set_id": quiz_set_id,
                    "variant_type": "mixed",
                    "total_marks": total_marks,
                }
            )
            .execute()
        )
        variant_id = variant.data[0]["id"]

        stored: list[dict] = []
        for index, q in enumerate(questions):
            question_row = (
                service.table("questions")
                .insert(
                    {
                        "tenant_id": profile.tenant_id,
                        "chapter_id": chapter_id,
                        "type": q.type,
                        "question_text": q.question_text,
                        "options": q.options,
                        "correct_answer": q.correct_answer,
                        "explanation": _prefix_pyq(q.explanation, q.is_pyq, q.year),
                        "difficulty": q.difficulty,
                        "marks": q.marks,
                        "source": "extracted",
                        "review_status": "pending_review",
                        "confidence_score": q.confidence,
                        "extraction_job_id": job_id,
                        "created_by": profile.user_id,
                    }
                )
                .execute()
            )
            question_id = question_row.data[0]["id"]
            created_question_ids.append(question_id)
            service.table("quiz_variant_questions").insert(
                {
                    "tenant_id": profile.tenant_id,
                    "variant_id": variant_id,
                    "question_id": question_id,
                    "order_index": index,
                }
            ).execute()
            stored.append({"id": question_id, **q.model_dump()})

        # 6) Close the job as succeeded.
        service.table("ai_extraction_jobs").update(
            {
                "status": "succeeded",
                "raw_output": raw,
                "model_used": provider,
                "overall_confidence": overall_confidence,
                "completed_at": _now(),
            }
        ).eq("id", job_id).eq("tenant_id", profile.tenant_id).execute()

        return {
            "quiz_set_id": quiz_set_id,
            "variant_id": variant_id,
            "provider": provider,
            "extraction_job_id": job_id,
            "extracted": len(stored),
            "skipped": skipped,
            "overall_confidence": overall_confidence,
            "questions": stored,
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("Quiz extraction failed (%s)", type(exc).__name__)
        # Compensate across PostgREST calls: no orphaned draft sets/questions.
        if quiz_set_id:
            (
                service.table("quiz_sets")
                .delete()
                .eq("id", quiz_set_id)
                .eq("tenant_id", profile.tenant_id)
                .execute()
            )
        if created_question_ids:
            (
                service.table("questions")
                .delete()
                .in_("id", created_question_ids)
                .eq("tenant_id", profile.tenant_id)
                .execute()
            )
        service.table("ai_extraction_jobs").update(
            {
                "status": "failed",
                "error_message": "Quiz extraction failed.",
                "completed_at": _now(),
            }
        ).eq("id", job_id).eq("tenant_id", profile.tenant_id).execute()
        raise
