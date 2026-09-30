# Handwritten evaluation Phase E: frozen rubric generation

Phase E builds one validated, machine-readable marking rubric when a teacher creates an evaluation paper. The same rubric is frozen on `evaluation_papers` and will be reused by the future scoring phase for every student; this phase does not grade submissions.

## Lifecycle

Migration 80 extends the existing `evaluation_jobs` queue with the teacher-owned `build_rubric` kind. An `AFTER INSERT` trigger creates exactly one job per paper. The partial unique index on `evaluation_paper_id`, row-locking queue claim, lease heartbeat, and owner/tenant checks prevent concurrent builds and cross-tenant access.

The paper moves through `not_started -> extracting -> generating -> ready`, or `failed`. Extracted question and optional suggested-answer text are cached. Typed PDFs use the existing pdfplumber extraction utility; image-only PDFs, PNGs, and JPEGs use the existing schema-constrained Gemini multimodal adapter.

`HANDWRITTEN_RUBRIC_PROVIDER` selects the preferred text provider and defaults to `gemini`. Existing provider fallback remains available. The official-answer path stores `rubric_source=official`; papers without an answer document store `rubric_source=ai_derived`.

## Safety gate

The local validator rejects non-verbatim or duplicate question references, unknown marks, invalid parent arithmetic, off-grid marks, vague or incorrectly summed criteria, malformed MCQs, and overwritten printed marks. Optional-paper structure is retained for review whenever it cannot be proved. A printed pick value is changed only for a single equal-mark optional group with exactly one whole-number correction matching the configured paper total.

The provider receives exactly one bounded semantic repair request containing the validation failures and its previous candidate as untrusted data. The repaired response passes through the same validator. A second invalid response permanently fails the job and no rubric is persisted.

