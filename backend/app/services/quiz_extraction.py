"""
Quiz EXTRACTION orchestration.

Reads an existing quiz document a teacher uploaded (typed PDF, scanned image, or
DOCX) and pulls the questions out with Gemini, then stores them as a DRAFT quiz
set whose questions are `pending_review` — so they flow through the SAME teacher
review -> publish path as generated quizzes. The teacher review gate is the
accuracy guarantee: students only ever see approved questions.

Deliberately separate from generation.py so the core generator is untouched.
  PDF / image  -> Gemini vision (bytes sent inline, no OCR needed)
  DOCX         -> extract text -> Gemini (text)

Raises ValueError for caller/input problems and LLMError for model problems; the
API layer maps those to HTTP status codes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

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
from app.services.llm.structured import gemini_json, gemini_json_multimodal
from app.services.teacher_access import teacher_has_subject

# Which uploads the extractor accepts, and how to hand each to Gemini.
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
_VISION_EXT = {"pdf": "application/pdf", **_IMAGE_MIME}  # sent inline to vision
_TEXT_EXT = {"docx"}  # extracted to text first


class ExtractedQuestion(GeneratedQuestion):
    """A generated-question shape plus extraction-only metadata."""

    confidence: float | None = None
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


def extract_quiz(
    *,
    document_id: str,
    subject_id: str,
    profile: CurrentProfile,
) -> dict:
    service = get_service_client()

    # 0) Authorise: the teacher must own the target subject (explicit assignment
    #    is authoritative — same rule the generator enforces).
    if not teacher_has_subject(service, profile, subject_id):
        raise ValueError("Subject not found.")

    # 1) Fetch the uploaded document, scoped to the caller.
    doc = (
        service.table("documents")
        .select("*")
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
        # 3) Read the document with Gemini — vision for PDF/images, text for DOCX.
        content = download_bytes(doc_row["storage_path"])
        if ext in _VISION_EXT:
            raw = gemini_json_multimodal(
                EXTRACTION_SYSTEM,
                EXTRACTION_USER_FILE,
                files=[(_VISION_EXT[ext], content)],
            )
        else:  # docx
            text = extract_text(content, ext)
            if not text.strip():
                raise ValueError("This document has no readable text.")
            raw = gemini_json(
                EXTRACTION_SYSTEM,
                build_extraction_user_text(text),
                model=settings.gemini_model,
                temperature=0.1,
            )

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
                    "chapter_id": doc_row.get("chapter_id"),
                    "subject_id": subject_id,
                    "title": f"{doc_row.get('original_filename', 'Quiz')} — Extracted",
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
                        "chapter_id": doc_row.get("chapter_id"),
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
                "overall_confidence": overall_confidence,
                "completed_at": _now(),
            }
        ).eq("id", job_id).execute()

        return {
            "quiz_set_id": quiz_set_id,
            "variant_id": variant_id,
            "provider": "gemini",
            "extraction_job_id": job_id,
            "extracted": len(stored),
            "skipped": skipped,
            "overall_confidence": overall_confidence,
            "questions": stored,
        }

    except Exception as exc:  # noqa: BLE001
        # Compensate across PostgREST calls: no orphaned draft sets/questions.
        if quiz_set_id:
            service.table("quiz_sets").delete().eq("id", quiz_set_id).execute()
        if created_question_ids:
            service.table("questions").delete().in_(
                "id", created_question_ids
            ).execute()
        service.table("ai_extraction_jobs").update(
            {
                "status": "failed",
                "error_message": str(exc)[:500],
                "completed_at": _now(),
            }
        ).eq("id", job_id).execute()
        raise
