# Durable document analysis and quiz-generation jobs

**Status:** implemented
**Verified against code:** 21 September 2026

This document replaces the older pre-build chunked-generation proposal. The
implemented system now prefers a cost-bounded one-call topic analysis for typed
documents, while retaining the multi-call map/reduce design as a compatibility
fallback. Final quiz generation is also a durable background job.

See `current-ai-document-workflow.md` for provider routing and document-type
detection.

## 1. Routing

`POST /api/v1/quiz-sets/analyze` creates a `quiz_generation_jobs` row and returns
the job immediately. The worker loads locally extracted text and follows:

```text
Readable PDF/DOCX
  ├─ reliable PDF index available and local outline enabled
  │    └─ local hierarchy, no AI call
  ├─ universal one-call analysis enabled (normal path)
  │    └─ one bounded DeepSeek-first request → local validation/evidence lookup
  └─ multi-call compatibility explicitly allowed
       └─ profile → chunk → map incomplete chunks → reduce
```

Document length no longer automatically means many provider calls. The normal
large typed-document route is the universal one-call analyzer. A table of
contents can improve the optional local route but is never required by the
universal route.

## 2. Universal one-call analysis

`single_call_document_outline.py` turns every PDF page, or each stable DOCX
source section, into an explicitly numbered location. It keeps the request under
a 600,000-character safety budget by sampling each location, with a larger
allowance for detected contents pages. The model returns at most 30 selectable
topics grouped under at most 12 navigation groups.

The model is not trusted to provide source prose. Local code validates and
normalizes topic names, covered concepts, source ranges, ordering, duplicates,
and evidence locations, then retrieves exact evidence excerpts from the original
extracted text. Topic count is adaptive; there is deliberately no minimum for a
small document.

## 3. Checkpoint and retry

Before local response processing, the raw successful one-call JSON is stored in
the job's `params.single_call_response_checkpoint`. This creates two retry cases:

- Failure before checkpoint: Retry must call the provider again.
- Failure after checkpoint: Retry supplies the saved response to local
  processing and incurs no repeat analysis call.

The frontend persists the job ID in current-tab `sessionStorage`, polls the
backend after refresh, and shows a Retry action for failed/partial jobs. The
database job is authoritative; browser storage only reconnects the UI.

## 4. Multi-call compatibility path

When enabled for a document that cannot use the preferred path:

1. A best-effort profile is generated once and stored in job params.
2. Text is split at structural boundaries with overlap and chunks are stored.
3. MAP calls run with bounded concurrency. Completed chunks stay completed.
4. Any failed chunk makes the job `partial`; topic selection is blocked.
5. Retry processes only queued/failed chunks.
6. REDUCE runs only after every chunk succeeds, preventing silent omissions.

The current chunk defaults are documented in `backend/.env.example`:
`GENERATION_CHUNK_CHARS=60000`, `GENERATION_CHUNK_OVERLAP_CHARS=5000`,
`GENERATION_CHUNK_MIN_CHARS=8000`, and `GENERATION_CHUNK_CONCURRENCY=4`.

## 5. Topic selection and source grounding

The completed master blueprint stores groups, topics, covered concepts, source
ranges, evidence, and per-topic capacity. Faculty select topics and exact
question-type counts. The backend reconstructs source material from those
ranges, so generation receives relevant document text in addition to topic
names. Capacity limits prevent requesting more distinct questions than the
available grounded material is expected to support.

## 6. Final generation job

Starting generation creates or reuses an idempotent final-phase job. A double
click, request retry, or browser refresh reconnects to the existing job rather
than creating duplicate provider calls or quiz sets. The worker generates and
validates the exact requested mix, persists the draft quiz atomically with
compensation on failure, and records `quiz_set_id` on completion.

Questions remain `pending_review`. No partial or failed job publishes questions
to students.

## 7. Status and failure semantics

| Status | Meaning | Faculty action |
|---|---|---|
| `queued` / `running` | Background work is active | Wait; refresh is safe |
| `partial` | Some compatibility MAP chunks failed; successful chunks are saved | Retry remaining sections |
| `failed` | Stage stopped safely | Retry; checkpointed work is reused where available |
| `completed` + analysis blueprint | Topics are ready | Select topics/counts |
| `completed` + `quiz_set_id` | Draft quiz is ready | Continue to review |

Jobs stuck longer than `GENERATION_CHUNK_STUCK_SECONDS` are converted to a
retryable failure when polled. Error messages stored for faculty are bounded and
must not expose provider secrets or raw credentials.

## 8. Cost and rate-limit behavior

- The normal one-call path consumes one topic-analysis provider call.
- Local PDF outline extraction consumes zero provider calls.
- Compatibility map/reduce consumes multiple calls and is not the default.
- A provider fallback is a separate logged attempt and may increase cost.
- AI call logs group all attempts by paper/job and record tokens, latency, model,
  fallback status, and estimated cost.
- Internal durable work is protected by the topic-extraction and generation rate
  limits; exact defaults live in `backend/.env.example`.

## 9. Main implementation files

| File | Responsibility |
|---|---|
| `backend/app/api/quiz.py` | analyze/status/retry/final-generation endpoints |
| `backend/app/services/generation_jobs.py` | durable orchestration and resume |
| `backend/app/services/local_document_outline.py` | optional zero-AI PDF outline |
| `backend/app/services/single_call_document_outline.py` | universal bounded analysis and checkpoint-aware processing |
| `backend/app/services/chunking_service.py` | persisted compatibility chunks |
| `backend/app/services/topic_extraction_pipeline.py` | compatibility MAP processing |
| `backend/app/services/master_blueprint_synthesizer.py` | compatibility REDUCE |
| `backend/app/services/source_material.py` | selected-range material assembly |
| `backend/app/services/quiz_generator_service.py` | grounded final generation |
| `frontend/components/teacher/blueprint-generator.tsx` | workflow state, polling, retry, and refresh reconnection |

## 10. Invariants

- No topic list or quiz may silently omit a failed document section.
- No retry should repeat completed/checkpointed work unnecessarily.
- Model output is validated before persistence.
- Selected topics are grounded in source ranges and evidence.
- AI drafts never bypass teacher review.
- Student grading remains deterministic and independent of this pipeline.
