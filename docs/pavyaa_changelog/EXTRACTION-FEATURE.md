# Quiz Extraction Feature — `extraction-pavyaa` branch

> **Historical branch handoff.** The feature remains, but current routing is:
> typed PDF/DOCX → local text extraction → DeepSeek first with Gemini fallback;
> scan/image → Gemini vision. For current behavior use
> `docs/current-ai-document-workflow.md`.

**Author:** (pavyaa)  ·  **Branch:** `extraction-pavyaa`  ·  **Status:** built + tested locally

A handoff doc so anyone can understand, run, and extend what this branch adds.
Everything here is **additive** — the existing quiz *generator*, review, and
publish flows are untouched.

---

## 1. What this branch adds (in one paragraph)
A teacher can **upload an existing quiz document** — a typed PDF, a scanned image,
or a DOCX — and the configured text/vision provider extracts the questions, options, and correct answers
into a **draft** quiz set (status `pending_review`) under a chosen **subject +
chapter**. It then flows through the **existing** teacher review → publish
pipeline, so students only ever see teacher-approved questions. Includes chapter
mapping, duplicate-file detection, and catalog (course/subject) de-duplication.

---

## 2. End-to-end flow
```
Teacher → "Extract quiz" page
  → pick Subject + Chapter (existing or create new)
  → upload file (PDF / DOCX / PNG / JPG, ≤20 MB)
        │
        ▼
POST /api/v1/quiz-sets/extract   (multipart: file, subject_id, chapter_id, force)
        │  • SHA-256 hash the file → if same file already uploaded and force=false → 409 (soft warning)
        │  • store file + documents row (with content_hash)
        ▼
quiz_extraction.extract_quiz()
        │  • authorise: teacher owns the subject (teacher_has_subject)
        │  • validate: chapter belongs to that subject + tenant
        │  • typed PDF/DOCX → local text → DeepSeek/Gemini fallback; scan/image → Gemini VISION (no OCR)
        │  • validate each question (skip malformed), compute confidence
        │  • persist: quiz_set(draft) → variant → questions(source='extracted',
        │             review_status='pending_review', chapter_id, confidence_score,
        │             extraction_job_id) → links   (+ ai_extraction_jobs audit row)
        ▼
redirect → /dashboard/teacher/review/{quiz_set_id}  (EXISTING review screen)
        → teacher edits / approves → Publish → students see it (existing RLS)
```

---

## 3. Backend changes

### New files
| File | Purpose |
|---|---|
| `backend/app/api/extraction.py` | The `POST /api/v1/quiz-sets/extract` endpoint (own router, teacher-only, multipart; accepts images which the shared `/documents` upload does not). Handles file hashing + duplicate `409`. |
| `backend/app/services/quiz_extraction.py` | Orchestrator `extract_quiz(...)`. Mirrors `generation.py`'s persistence + rollback. Local text path for typed PDF/DOCX; Gemini vision for scans/images. Records an `ai_extraction_jobs` row. |
| `backend/app/services/extraction_prompts.py` | The verbatim-extraction prompt + output contract. Handles answers marked inline / "Answer: C" / an end-of-doc answer key, plus PYQ/year tags. Objective question types only. |

### Modified files
| File | Change |
|---|---|
| `backend/app/services/llm/structured.py` | Adds `gemini_json_multimodal(system, user, files, ...)` for PDF/image bytes while preserving the shared text fallback path from `main`. |
| `backend/app/main.py` | Mounts the new `extraction.router`. |
| `backend/app/api/academics.py` | `create_course` + `create_subject` are now **get-or-create** (reuse an existing one by name instead of duplicating) — matching how `create_chapter` already worked. |

### The endpoint
```
POST /api/v1/quiz-sets/extract        (teacher only, multipart/form-data)
  file        : the quiz document (pdf|docx|png|jpg|jpeg, ≤ 20 MB)
  subject_id  : subject the quiz belongs to (teacher must own it)
  chapter_id  : chapter under that subject (required)
  force       : bool — "yes, extract even though it's a duplicate file"
→ 200 { quiz_set_id, variant_id, provider, extraction_job_id,
        extracted, skipped, overall_confidence, questions[] }
→ 409  when the exact file was already uploaded (soft warning; retry with force=true)
```

### Key implementation notes
- **AI routing:** typed extraction follows `TYPED_QUIZ_EXTRACTION_PROVIDER`
  (DeepSeek by default) with `AI_FALLBACK_PROVIDER` (Gemini by default). Scanned
  PDFs/images use `GEMINI_MODEL` vision. No OCR dependency is installed.
- **Accuracy guarantee = the review gate.** Extraction is never trusted blindly: questions land as `pending_review`; the teacher reviews/edits before publish. Per-question `confidence_score` is stored (low = scrutinise).
- **Mapping guarantee:** the chapter is validated to belong to the subject + tenant; the resolved `chapter_id` is written to the quiz set, **every** question, and the source document → clean `Subject → Chapter → Questions`.
- **Duplicate guard is a *soft warning*, not a block** — multiple different quizzes per chapter are still allowed; only the exact same file re-upload is flagged.

---

## 4. Frontend changes

### New files
| File | Purpose |
|---|---|
| `frontend/app/dashboard/teacher/extract/page.tsx` | Thin page wrapper. |
| `frontend/components/teacher/quiz-extractor.tsx` | The extractor UI: subject select → chapter dropdown (existing or "+ Add new chapter") → file upload → "Extract quiz". Shows the AI-reading state, the duplicate warning + "Extract anyway", and redirects to the review screen on success. |

### Modified files
| File | Change |
|---|---|
| `frontend/lib/api.ts` | `extractQuiz(file, subjectId, chapterId, force?)`, the `ExtractResult` type, and `DuplicateFileError` (thrown on `409`). |
| `frontend/components/shared/dashboard-shell.tsx` | Adds the **"Extract quiz"** nav item (teacher, Content section, Sparkles icon). |
| `frontend/components/student/student-quizzes.tsx` | Student quiz cards now show a **`Subject · Chapter`** line so students see which chapter a quiz is from. |

---

## 5. Database migrations (run in Supabase SQL Editor, in order)
All are **additive** (no existing column/row changed). Run any dup-check queries noted in each file first.

| Migration | What it does | Required? |
|---|---|---|
| `migrations/migration-15-quiz-extraction.sql` | Adds `'extracted'` to the `question_source` enum (tags extracted questions). | **Required** — extraction inserts `source='extracted'`. |
| `migrations/migration-16-chapter-uniqueness.sql` | Unique index `chapters(tenant_id, subject_id, name)`. | Recommended (DB backstop for chapter dedup). |
| `migrations/migration-17-document-hash.sql` | Adds `documents.content_hash` + index (duplicate-file detection). | **Required** — extraction writes/queries `content_hash`. |
| `migrations/migration-18-course-subject-uniqueness.sql` | Unique indexes on `courses(tenant_id,name)` and `subjects(tenant_id,course_id,name)`. | Recommended (DB backstop for catalog dedup). |
| `migrations/migration-19-quiz-extraction-rate-limit.sql` | Adds `quiz_extraction` to the shared per-user AI rate limiter. | **Required** — the endpoint fails closed if rate limiting is unavailable. |
| `migrations/migration-23-quiz-set-document-link.sql` | Links each new quiz set to its source document for log status and retry tracking. | **Required** — generation and extraction write `quiz_sets.document_id`. |

> **Reuses existing schema (no change):** `questions.chapter_id`, `questions.confidence_score`, `questions.extraction_job_id`, and the `ai_extraction_jobs` table already existed — extraction just started populating them.

---

## 6. Configuration
- **`backend/.env`** → `GEMINI_API_KEY=...` for PDF/image extraction, `DEEPSEEK_API_KEY=...` for DOCX fallback, and optionally `RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR=10`.
- **`frontend/.env.local`** → `NEXT_PUBLIC_API_BASE_URL=http://localhost:8001` for local. `.env.local` is gitignored — copy the format from `.env.local.example`. **NEXT_PUBLIC_* vars bake at server start → restart the frontend after changing them.**

---

## 7. Run & test locally
```powershell
# Backend (port 8001)
cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8001
# Frontend (port 3001)
cd frontend; pnpm install; pnpm dev --port 3001
```
1. Run migrations **15–19**, then **23**, in order. Run the duplicate prechecks in 16 and 18 before their indexes.
2. Log in as a teacher who has an assigned subject → sidebar **Extract quiz**.
3. Pick subject + chapter (or add a new chapter), upload an MCQ file → **Extract quiz** → lands on the Review screen.
4. Approve/publish → switch to a student → the quiz shows its **chapter name** + `Subject · Chapter`.
5. Re-upload the **same file** → you get the "already uploaded… extract anyway?" warning.

---

## 8. Design decisions
- **New files, not edits to the generator** — `generation.py` and the review/publish endpoints are untouched.
- **Human-in-the-loop** is the accuracy guarantee (extraction → review → publish).
- **Soft warnings over hard blocks** for duplicates, so legitimate multi-uploads still work.
- **Reuse over duplicate** for course/subject/chapter (get-or-create) with DB unique-index backstops.

## 9. Possible follow-ups (not built)
- **Level-2 duplicate detection:** compare extracted *questions* to existing ones (normalised text or the unused `questions.embedding` pgvector column) to catch re-scans / same-content-different-file.
- **Per-question chapter detection** for documents spanning multiple chapters (v1 files the whole upload under one chapter).
- Surface `confidence_score` visually in the review card (highlight low-confidence questions).
- Apply the file-hash duplicate guard to the generation upload path too.

---

## 10. Integration status

The teammate implementation is integrated on `akbar/quiz-extraction-integration`
with current `main`. Its migration numbers, validation, timeout, fallback,
rate-limiting, and test coverage were updated during integration review.
