# Handwritten evaluation Phase B: Stage 1

Phase B performs transcription only. It reads the student's original private
PDF/JPEG/PNG and stores a structured extraction in
`handwritten_submissions.stage1_extraction`; it does not score answers, create a
rubric, identify mistakes, or write analytics.

The extraction contract contains `text_answers`, `tables`,
`numerical_workings`, `page_manifest`, and `legibility_report`. A linked
generated paper supplies a canonical question guide when its structured payload
is available. Standalone faculty-uploaded papers intentionally use the degraded,
guide-free path. Unlike ExamApp, quiz-generator does not yet have a SubjectSkill
model, so its grading-blind subject structure profile is deliberately omitted.
That is a known simplification, not an extraction failure.

The deterministic post-processing order is visible-heading precedence,
page-manifest fallback, exact leading-continuation merge, row-reference table
splitting, invalid-reference snap/quarantine, then legibility sanitization.
Physical missing/duplicate/unreadable pages alone trigger one focused reread,
bounded to six pages and rendered from the original stored PDF as lossless
300-DPI PNGs. Other page disagreements remain audit telemetry. Unresolved pages
are retained as scoreable evidence, marked `page_verification_uncertain`, and
routed to review.

As in ExamApp, review routing is normally a post-grading state: unresolved
physical-page or legibility-metadata uncertainty continues through Stage 2,
creates the report, and marks that completed report for faculty review. Only a
script whose overall legibility is `illegible` stops before scoring. A
page-manifest/question-reference disagreement by itself neither triggers another
paid read nor blocks grading.

Stage 1 uses Gemini JSON mode at temperature `0.0`. Its dedicated
`GEMINI_STAGE1_MODEL` defaults to `gemini-2.5-flash`, matching ExamApp's proven
handwritten extraction path without changing other Gemini workflows. Configure
the output and reasoning budgets with `GEMINI_STAGE1_MAX_OUTPUT_TOKENS` (default
`32000`) and `GEMINI_STAGE1_THINKING_BUDGET` (default `4000`). Automatic queue
retries reuse the cached extraction only when `stage1_extraction_source` exactly
matches the current storage path. An explicit re-evaluation always performs a
fresh read.

Native evidence follows ExamApp's transport boundary. Files whose encoded body
exceeds 10,000,000 base64 characters, or that would push cumulative inline
evidence above 18,000,000 characters, are uploaded unchanged with Gemini's
resumable Files API. The worker waits for the file to become `ACTIVE` and sends
its `file_uri` to `generateContent`. If upload/readiness fails, complete inline
fallback is allowed only while the cumulative safe inline budget still fits;
the worker never omits an oversized answer script merely to continue evaluation.
