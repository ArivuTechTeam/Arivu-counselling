# Current AI and document workflow

**Verified against code:** 21 September 2026
**Applies to:** topic analysis, quiz generation, quiz extraction, question
verification/regeneration, and the teacher Generate Quiz workflow.

This is the short authoritative reference for the cost-optimized implementation.
The environment template in `backend/.env.example` remains the source of truth
for configurable defaults.

## 1. Provider routing

Text work is stage-aware. Current defaults are:

| Stage | Preferred provider | Fallback |
|---|---|---|
| Topic analysis, including the one-call outline and map/reduce compatibility path | DeepSeek | Gemini |
| Standard and blueprint quiz generation | DeepSeek | Gemini |
| Typed existing-quiz extraction | DeepSeek | Gemini |
| Question verification | DeepSeek | Gemini |
| Question regeneration | DeepSeek | Gemini |
| Scanned PDF/image extraction | Gemini vision | None |
| AI Tutor explanation | Gemini compatibility default | DeepSeek |

The preferred providers are controlled by `TOPIC_ANALYSIS_PROVIDER`,
`QUIZ_GENERATION_PROVIDER`, `TYPED_QUIZ_EXTRACTION_PROVIDER`,
`QUESTION_VERIFICATION_PROVIDER`, and `QUESTION_REGENERATION_PROVIDER`.
`AI_FALLBACK_PROVIDER` defaults to `gemini`. `VISION_EXTRACTION_PROVIDER` must
remain `gemini` until a DeepSeek multimodal adapter exists.

If a preferred API key is absent, the router skips that provider and uses an
available configured provider. HTTP errors, provider errors, invalid JSON, and
non-object JSON can activate the controlled fallback. DeepSeek thinking is off
by default to avoid hidden reasoning cost and latency.

## 2. How document type is decided

The file extension alone does not decide the AI path.

- Typed PDF: `pdfplumber` extracts a usable text layer locally.
- DOCX: `python-docx` extracts text locally.
- Scanned/image PDF or PNG/JPG: little or no usable text is available, so the
  existing-quiz Extract flow sends bytes to Gemini vision. A PDF with a
  substantial image-only section (at least two sparse image pages covering at
  least 20% of its pages) is also treated as mixed/scanned.
- The ordinary Generate Quiz upload accepts PDF/DOCX and requires readable
  text. A scan with insufficient text is rejected with guidance to use Extract
  Quiz. No OCR library is installed.

An isolated blank cover or decorative image does not force an otherwise typed
PDF through full-document vision. Images embedded in an otherwise typed teaching
PDF are not interpreted for quiz generation in Phase 1. Diagram/puzzle-aware image extraction was intentionally
deferred to Phase 2. The current quiz must therefore be grounded in the
extracted text, except when the separate scanned existing-quiz vision path is
used.

## 3. Topic analysis for large typed documents

The teacher uploads or selects a stored document, then starts analysis. The
backend creates a durable `quiz_generation_jobs` record and uses this order:

1. If a typed PDF has a reliable index/heading structure, the optional local
   outline builder may create the hierarchy without an AI call.
2. Otherwise, the universal one-call analyzer represents every page (or stable
   DOCX source section) inside a bounded request. It asks for navigation groups,
   independently selectable topics, covered concepts, source ranges, and
   evidence locations. A contents page is a hint, not a requirement.
3. Topic count is derived from the material. There is no fixed minimum; short
   documents can return one or two topics. The response is capped at 30 topics.
4. The backend validates names, ranges, ordering, evidence locations, duplicate
   concepts, and source grounding locally. Exact supporting excerpts are
   retrieved from the original extracted text, not invented by the model.
5. The older multi-call profile/map/reduce pipeline remains a compatibility
   fallback only when explicitly allowed.

This gives faculty a compact, selectable hierarchy rather than hundreds of
isolated terms while keeping the usual analysis to one provider call.

## 4. Quiz generation context

Topic analysis does not replace the source document. When faculty select topics
and question counts, the backend resolves the selected topics to their source
ranges and constructs grounded material from those ranges. The generation model
therefore receives both the exact plan and the relevant source text. It does not
generate from topic names alone.

Generated questions are validated for schema, requested type/count distribution,
answer shape, topic grounding, and source support. They are persisted as
`pending_review`; faculty approval remains mandatory before students can see
them. Ordinary quiz grading is deterministic and never calls an LLM. The
separately gated paper bank uses a bounded, quota-limited AI call only for
descriptive student answers, after teacher approval; objective answers remain
deterministic.

## 5. Durable retry and refresh behavior

- The backend stores the analysis job, checkpoints the raw one-call response
  before local post-processing, and stores completed map chunks in the
  compatibility path.
- If post-processing fails after a provider response was saved, Retry reuses the
  checkpoint and does not repeat the paid analysis call.
- If a compatibility map job is partial, successful chunks remain saved and
  Retry processes only queued/failed chunks. Topic selection stays blocked until
  coverage is complete.
- Final quiz generation also uses a durable background job with idempotent job
  creation, so refresh/double-click does not create a second quiz job.
- The optional `faculty_jobs` queue extends that recovery to final generation
  and quiz import. It remains off until migration 43 is applied and a separate
  worker process is deployed; with the flag off, the established paths remain.
- The teacher page stores the current workflow/job identifiers and form state in
  the current tab's `sessionStorage`, reconnects to the durable backend job after
  refresh, and clears the saved workflow after completion or an explicit reset.
- The upload area says “Uploading document…” during the upload. Analysis labels
  are shown only after analysis actually starts.

Browser storage is a recovery aid, not the source of truth. Durable progress is
stored in Supabase job rows.

## 6. Cost controls and observability

- Typed text is extracted locally; raw typed files are not sent to a vision
  model.
- The normal large-document topic path is one bounded AI call rather than a call
  per chunk.
- Only selected topic ranges are sent for final generation.
- DeepSeek is preferred for paid text stages and thinking is disabled by default.
- Provider attempts, input/output/cached/thinking tokens, model, fallback status,
  latency, result, and estimated USD cost are logged. The super-admin page
  converts USD using a user-editable, tab-persisted INR rate; this display value
  does not alter provider billing.

A local 300-page networking run recorded approximately ₹3.97 for topic analysis,
₹0.88 for generation, and ₹0.14 for verification (about ₹5 total at that view's
conversion rate). This is evidence from one run, not a price guarantee: document
text density, selected topics, output size, fallback use, provider prices, and
the display conversion rate can change the total.

## 7. Failure policy

- Missing readable text: reject the Generate Quiz upload and direct scans to the
  Extract Quiz vision flow.
- Preferred text provider fails or returns invalid JSON: try the configured
  fallback and log both attempts.
- Vision extraction fails: store a failed extraction job; Retry reuses the
  stored document, but Gemini vision must be called again because no successful
  response checkpoint exists.
- One-call analysis fails before a response checkpoint: Retry calls the provider
  again. If it fails after the checkpoint, Retry resumes local processing.
- Final generation fails: keep a safe retryable job state and do not publish or
  expose partial questions.

Production behavior still depends on Railway having the documented keys and
stage-routing variables. Repository state alone does not prove deployed values
or provider health.
