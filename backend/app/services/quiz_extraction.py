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
  Typed PDF / DOCX (has a text layer) -> extract text -> DeepSeek + Gemini fallback
  Scanned PDF / image (no text layer) -> Gemini vision (bytes inline, no OCR)

Raises ValueError for caller/input problems and LLMError for model problems; the
API layer maps those to HTTP status codes.
"""

from __future__ import annotations

import logging
from typing import Literal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

from app.lib.auth import CurrentProfile
from app.lib.config import get_settings
from app.lib.storage import download_bytes
from app.lib.supabase import get_service_client
from app.services.extraction import MIN_READABLE_PDF_TEXT_CHARS, extract_text, extract_text_with_pages
from app.services.import_fidelity import inventory, question_chunks, reconcile
from app.services.extraction_prompts import (
    EXTRACTION_USER_FILE,
    PYQ_CONTEXT_SYSTEM,
    build_extraction_user_text,
    build_pyq_context_user,
    extraction_system,
)
from app.services.generation import GeneratedQuestion
from app.services.ai_call_logging import ai_call_context
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


class ExtractedQuestion(GeneratedQuestion):
    """A generated-question shape plus extraction-only metadata."""

    # Extraction may additionally pull DESCRIPTIVE questions (paper mode only);
    # generation never does, so this widening is extraction-scoped.
    type: Literal[  # type: ignore[assignment]
        "mcq_single", "mcq_multi", "true_false", "numerical", "fill_blank", "descriptive"
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_pyq: bool = False            # base contract (normal extraction / off path)
    year: str | None = None
    # Paper-analysis mode (teacher opted in):
    paper_type: str | None = None   # 'pyq' | 'mtp' | 'rtp'
    exam: str | None = None
    paper_source_note: str | None = None
    model_answer: str | None = None    # descriptive: suggested answer from the document
    answer_summary: str | None = None  # descriptive: AI key-point summary (for grading)
    source_number: str | None = None
    verification_status: str = "needs_teacher_review"
    verification_warnings: list[str] = Field(default_factory=list)


class ExtractedQuiz(BaseModel):
    questions: list[ExtractedQuestion]


def _validate_import_candidates(raw: dict) -> tuple[list[ExtractedQuestion], dict]:
    """Account for every model candidate without claiming full source coverage."""
    candidates = raw.get("questions") or []
    if not isinstance(candidates, list):
        raise LLMError("Extraction returned an invalid question list.")
    questions: list[ExtractedQuestion] = []
    issues: list[dict] = []
    for index, candidate in enumerate(candidates, start=1):
        try:
            question = ExtractedQuestion.model_validate(candidate)
            question.verification_status = "needs_teacher_review"
            if not question.verification_warnings:
                question.verification_warnings = ["Imported answer is unconfirmed; compare with the original paper before approval."]
            if question.type == "descriptive":
                # Descriptive questions have no auto-gradeable answer; they carry a
                # model answer instead and are graded by AI later. Give correct_answer
                # a non-null placeholder so the (NOT NULL) questions column accepts it.
                if not (question.model_answer and question.model_answer.strip()):
                    raise ValueError("Descriptive question has no model answer.")
                if question.correct_answer is None:
                    question.correct_answer = {"model_answer": question.model_answer}
            else:
                question.check_shape()
            if not question.question_text.strip():
                raise ValueError("Question text is empty.")
            questions.append(question)
        except (ValidationError, ValueError) as exc:
            reason = "Question fields are missing or invalid." if isinstance(exc, ValidationError) else str(exc)
            issues.append({
                "candidate_index": index,
                "question_preview": str(candidate.get("question_text") or "")[:240] if isinstance(candidate, dict) else "",
                "reason": reason,
            })
    source_inventory = raw.get("source_inventory")
    if isinstance(source_inventory, dict):
        invalid = {issue["candidate_index"] for issue in issues}
        source_inventory = {**source_inventory, "items": [
            {**item, "state": "unresolved" if item["candidate_index"] in invalid else "imported"}
            for item in source_inventory.get("items", [])]}
    return questions, {
        "candidates": len(candidates), "imported": len(questions),
        "skipped": len(issues), "issues": issues,
        "coverage_verified": False,
        "source_inventory": source_inventory,
        "source_manifest": raw.get("source_manifest"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefix_pyq(explanation: str | None, is_pyq: bool, year: str | None) -> str | None:
    """v1: carry PYQ/year in the explanation text. Used ONLY when PYQ is off; with
    PYQ on, year/exam live in dedicated columns and the explanation is left clean."""
    if not is_pyq:
        return explanation
    tag = f"[PYQ {year}]" if year else "[PYQ]"
    return f"{tag} {explanation}".strip() if explanation else tag


def _pyq_on() -> bool:
    return getattr(get_settings(), "paper_bank_enabled", False)


def pyq_insert_fields(question, paper_mode: bool = False) -> dict:
    """The explanation + paper columns for a question insert. Outside paper mode
    (normal extraction / flag off / teacher said No) this is byte-identical to
    today (legacy explanation-prefix, no paper columns). In paper mode the question
    carries a classified paper_type and the paper_* columns are written."""
    if not paper_mode:
        return {"explanation": _prefix_pyq(question.explanation, question.is_pyq, question.year)}
    paper_type = getattr(question, "paper_type", None) or ("pyq" if question.is_pyq else None)
    return {
        "explanation": question.explanation,
        "paper_type": paper_type,
        "paper_year": (question.year or None) if paper_type else None,
        "paper_exam": (getattr(question, "exam", None) or None) if paper_type else None,
        "paper_source_note": (getattr(question, "paper_source_note", None) or None) if paper_type else None,
        "model_answer": (getattr(question, "model_answer", None) or None) if paper_type else None,
        "answer_summary": (getattr(question, "answer_summary", None) or None) if paper_type else None,
    }


def detect_pyq_context(
    text: str, *, tenant_id: str | None = None, document_id: str | None = None,
    job_id: str | None = None,
) -> dict | None:
    """Best-effort document-level PYQ context for LARGE (chunked) papers, so a
    banner/heading on the first or last page still reaches questions extracted from
    other chunks. Scans only the head + tail (where such markers live). Returns
    {"exam", "year"} or None; never raises - detection is a bonus, not a gate."""
    head_tail = text[:6000] + ("\n...\n" + text[-4000:] if len(text) > 10000 else "")
    try:
        with ai_call_context(
            "pyq_context", tenant_id=tenant_id, document_id=document_id, job_id=job_id
        ):
            raw, _provider = complete_json_with_fallback(
                PYQ_CONTEXT_SYSTEM,
                build_pyq_context_user(head_tail),
                preferred_provider=getattr(
                    get_settings(), "typed_quiz_extraction_provider", "deepseek"
                ),
            )
        if not isinstance(raw, dict) or not raw.get("is_pyq_paper"):
            return None
        exam = (raw.get("exam") or "").strip() or None
        year = (raw.get("year") or "").strip() or None
        return {"exam": exam, "year": year} if (exam or year) else None
    except Exception:  # noqa: BLE001 - detection is best-effort
        return None


def _vision_extract(
    mime_type: str, content: bytes, *, tenant_id: str | None = None,
    document_id: str | None = None, job_id: str | None = None, paper_mode: bool = False,
) -> tuple[dict, str]:
    """Read a scanned page/image with Gemini vision (the only path that can)."""
    with ai_call_context(
        "quiz_extraction", tenant_id=tenant_id, document_id=document_id, job_id=job_id
    ):
        raw = gemini_json_multimodal(
            extraction_system(paper_mode),
            EXTRACTION_USER_FILE,
            files=[(mime_type, content)],
        )
    return raw, "gemini-vision"


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Keep complete question blocks together or reject an oversized block."""
    return question_chunks(text, max_chars)


def _merge_questions(results: list[dict]) -> list[dict]:
    """Preserve source occurrences in chunk order, including repeated stems.

    Chunks do not overlap and we have no reliable source occurrence IDs yet.
    Even identical content can occur in different paper sections; text equality
    is insufficient evidence to delete an imported question. Invalid candidates
    also pass through so validation can account for them in the import receipt.
    """
    return [q for result in results for q in (result.get("questions") or [])]


def _extract_text_chunk(
    chunk: str, *, tenant_id: str | None = None, document_id: str | None = None,
    job_id: str | None = None, pyq_context: dict | None = None, paper_mode: bool = False,
) -> tuple[dict, str]:
    """Extract one text chunk, retrying once on a transient model error so a
    single blip doesn't fail the whole (multi-chunk) document."""
    last_error: LLMError | None = None
    for _ in range(2):
        try:
            with ai_call_context(
                "quiz_extraction", tenant_id=tenant_id, document_id=document_id, job_id=job_id
            ):
                return complete_json_with_fallback(
                    extraction_system(paper_mode),
                    build_extraction_user_text(chunk, pyq_context),
                    preferred_provider=getattr(
                        get_settings(), "typed_quiz_extraction_provider", "deepseek"
                    ),
                )
        except LLMError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _text_extract(
    text: str, *, tenant_id: str | None = None, document_id: str | None = None,
    job_id: str | None = None, page_spans: tuple = (), paper_mode: bool = False,
) -> tuple[dict, str]:
    """Parse locally extracted text with the configured text provider and fallback.

    Small documents go in one call. Large ones (120-150+ pages) are split into
    bounded chunks extracted in parallel, then merged in source order — so no
    single call has a huge, slow, timeout-prone output.
    """
    text = text.strip()
    if not text:
        raise ValueError("This document has no readable text.")

    settings = get_settings()
    chunk_chars = settings.extraction_text_chunk_chars
    source = inventory(text)
    for item in source["items"]:
        pages = [span.page_number for span in page_spans
                 if span.char_start < item["offset"] + len(item["text"]) and span.char_end > item["offset"]]
        if pages:
            item.update(page_start=min(pages), page_end=max(pages))
    if len(text) <= chunk_chars:
        # Single call sees the whole paper, so no separate context pass is needed.
        with ai_call_context(
            "quiz_extraction", tenant_id=tenant_id, document_id=document_id, job_id=job_id
        ):
            raw, provider = complete_json_with_fallback(
                extraction_system(paper_mode),
                build_extraction_user_text(text),
                preferred_provider=getattr(
                    settings, "typed_quiz_extraction_provider", "deepseek"
                ),
            )
        return reconcile(raw, source), provider

    # Chunked (large paper): resolve the document-level paper context ONCE so a
    # first/last-page marker reaches every chunk. Best-effort, only in paper mode.
    pyq_context = (
        detect_pyq_context(text, tenant_id=tenant_id, document_id=document_id, job_id=job_id)
        if paper_mode else None
    )
    chunks = _chunk_text(text, chunk_chars)
    workers = max(1, min(settings.extraction_chunk_concurrency, len(chunks)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map preserves input order; any chunk that still fails after its retry
        # raises here, which cleanly aborts the whole job (no partial quiz).
        pairs = list(
            pool.map(
                lambda chunk: _extract_text_chunk(
                    chunk, tenant_id=tenant_id, document_id=document_id,
                    job_id=job_id, pyq_context=pyq_context, paper_mode=paper_mode,
                ),
                chunks,
            )
        )

    merged = _merge_questions([raw for raw, _ in pairs])
    provider = pairs[0][1] if pairs else "text"
    return reconcile({"questions": merged}, source), f"{provider} (chunked x{len(chunks)})"


def _extract_document_content(
    *, content: bytes, ext: str, tenant_id: str | None = None,
    document_id: str | None = None, job_id: str | None = None, paper_mode: bool = False,
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
        return _vision_extract(
            _IMAGE_MIME[ext], content, tenant_id=tenant_id, document_id=document_id,
            job_id=job_id, paper_mode=paper_mode,
        )

    # DOCX: always has a text layer.
    if ext == "docx":
        return _text_extract(
            extract_text(content, "docx"), tenant_id=tenant_id, document_id=document_id,
            job_id=job_id, paper_mode=paper_mode,
        )

    # PDF: prefer the text path when it's a typed document; fall back to vision
    # when there's little/no extractable text (a scanned image PDF) or the text
    # layer can't be read at all.
    if ext == "pdf":
        try:
            extracted = extract_text_with_pages(content, "pdf")
            text = extracted.text
        except Exception:  # noqa: BLE001 - unreadable text layer -> treat as scanned
            return _vision_extract(
                "application/pdf", content, tenant_id=tenant_id,
                document_id=document_id, job_id=job_id, paper_mode=paper_mode,
            )
        pages = [{"page": span.page_number,
                  "text_characters": len(text[span.char_start:span.char_end].strip()),
                  "has_images": span.has_images}
                 for span in extracted.page_spans]
        sparse = [page["page"] for page in pages if page["text_characters"] < 40]
        image_sparse = [page["page"] for page in pages
                        if page["has_images"] and page["text_characters"] < 40]
        # A blank/decorative cover must not send an otherwise typed 300-page PDF
        # through expensive vision. Route to vision when the document has no
        # usable text layer, or when image-only pages form a meaningful mixed
        # document segment. Image-aware question generation remains Phase 2.
        image_ratio = len(image_sparse) / max(1, len(pages))
        use_vision = (
            len(text.strip()) < MIN_READABLE_PDF_TEXT_CHARS
            or (len(image_sparse) >= 2 and image_ratio >= 0.20)
        )
        if use_vision:
            raw, provider = _vision_extract(
                "application/pdf", content, tenant_id=tenant_id,
                document_id=document_id, job_id=job_id, paper_mode=paper_mode,
            )
        else:
            raw, provider = _text_extract(
                text, tenant_id=tenant_id, document_id=document_id,
                job_id=job_id, page_spans=extracted.page_spans, paper_mode=paper_mode,
            )
        return {**raw, "source_manifest": {"pages": pages, "route": "vision" if use_vision else "text",
                "sparse_pages": sparse, "coverage_verified": False}}, provider

    raise ValueError(f"Unsupported file type for extraction: {ext or 'unknown'}")


def extract_quiz(
    *,
    document_id: str,
    subject_id: str,
    chapter_id: str,
    profile: CurrentProfile,
    analyze_papers: bool = False,
) -> dict:
    service = get_service_client()
    paper_mode = _pyq_on() and bool(analyze_papers)

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

    # 2) Open an extraction job (audit + confidence trail).
    job = (
        service.table("ai_extraction_jobs")
        .insert(
            {
                "tenant_id": profile.tenant_id,
                "document_id": document_id,
                "status": "running",
                # The final provider/model is written after content inspection:
                # typed documents use the text router, scans use Gemini vision.
                "model_used": "pending-content-routing",
            }
        )
        .execute()
    )
    job_id = job.data[0]["id"]

    quiz_set_id: str | None = None
    created_question_ids: list[str] = []
    try:
        # 3) Extract typed PDF/DOCX locally then use the text router. Only scans
        # and images go through Gemini vision.
        content = download_bytes(doc_row["storage_path"])
        raw, provider = _extract_document_content(
            content=content,
            ext=ext,
            tenant_id=profile.tenant_id,
            document_id=document_id,
            job_id=job_id,
            paper_mode=paper_mode,
        )

        # 4) Validate per-question; skip malformed ones (teacher reviews the rest).
        questions, import_summary = _validate_import_candidates(raw)
        skipped = import_summary["skipped"]
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
                        **pyq_insert_fields(q, paper_mode),
                        "difficulty": q.difficulty,
                        "marks": q.marks,
                        "source": "extracted",
                        "review_status": "pending_review",
                        "confidence_score": q.confidence,
                        "source_excerpt": q.source_excerpt,
                        "source_page_start": q.source_page_start,
                        "source_page_end": q.source_page_end,
                        "verification_status": "needs_teacher_review",
                        "verification_warnings": q.verification_warnings,
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
                "raw_output": {**raw, "import_summary": import_summary},
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
            "import_summary": import_summary,
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
