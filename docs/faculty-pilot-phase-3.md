# Phase 3: source fidelity and candidate repair

Approval policy update: the founder subsequently removed mandatory review notes
and enabled approval regardless of AI warnings. See [current approval workflow](faculty-approval-workflow.md).

This increment builds on the tested background worker and existing faculty review
workflow. It requires updated backend/worker and frontend code, but no new SQL
migration. Existing quizzes are not rewritten. Teacher approval and publication
rules remain unchanged.

## Implemented behavior

- Numbered text papers get an independent source inventory before model parsing.
  Matching uses exact normalized stem text; repeated occurrences are retained.
  The receipt shows detected items, candidate matches, missing matches, invalid
  matched candidates, repeated matches, source numbers, and answer provenance.
- A conservative answer-key join supports lettered single-choice options and
  simple inline/end-of-paper keys. Source numbering must be unambiguous and the
  returned option order and text must match before a source key is applied.
  A conflicting model answer is explicitly recorded; the item still requires
  teacher review. Conflicting source keys and section-ambiguous keys are not
  silently resolved. Multi-answer/numeric keys require teacher comparison.
- Long imports split at numbered item boundaries rather than arbitrary character
  offsets. An oversized question/unstructured block fails explicitly with advice
  to split the paper into complete sections. End keys are joined after all chunks
  return, so they need not share a model context with the question.
- PDF import records page text counts and processing route. A page with fewer
  than 40 readable characters sends the complete PDF through the existing vision
  route, preventing a readable first page from hiding a later scan. This can
  increase provider cost, including for blank separator pages. It does not prove
  visual extraction completeness. Page references are attached to uniquely
  matched text questions using the original extraction offsets.
- Text-only generation/large-document analysis rejects detected image pages with
  fewer than 40 readable characters. Direct blueprint generation rejects sources
  larger than its configured character limit instead of silently clipping them.
- Verification includes bounded original context around an excerpt; consolidated
  blueprint summaries are not presented as original evidence. Duplicate/missing
  verifier indices fail safely to review. Missing page references are identified
  as a review concern, rather than incorrectly asserting unsupported content.
- One repair pass attempts at most six unsupported/ambiguous generated candidates.
  It preserves type, topic and marks, validates wording, and reverifies the full
  proposed batch. The pass is accepted only if all replacements are verified and
  no retained question's verification status worsens. Otherwise the original draft
  and warnings remain. A verifier outage alone does not trigger repairs.
- The writer can explicitly report insufficient source capacity; the application
  stops rather than requesting padding. This is a model-reported limitation, not
  a measured bound on the source. The synchronous error recommends a lower count
  or more material; the current queued-job failure screen retains its generic
  source/selection failure message.

The main blueprint paths (direct and completed large-document analysis) use
selective repair. Legacy generic generation and individual regeneration are not
migrated into this repair pass. Imports never generate replacement questions.

## Supported-input limits

The independent inventory recognizes numbered questions with separate lettered
option lines. It does not establish full recall for unnumbered, numeric-option,
multi-column, shared-case, or image layouts. A zero inventory count means the
layout was not recognized, not that the source contained zero questions.
Repeated numbering, interleaved section keys, reformatted stems and multiline
options may require manual reconciliation. Receipts always retain
`coverage_verified=false`; matching candidates is not a proof of source recall.

Existing DOCX paragraph/table order and notation handling remain. Bold/underline-
only keys are not independently verified, PDF reading order is not reconstructed,
and embedded diagrams are not yet delivered to students. These require source
comparison and the planned media/layout work. No general OCR or diagram-fidelity
claim is made. An absent/invalid answer can remain a skipped candidate in the
receipt rather than an editable question; faculty must not interpret a draft as
a complete copy of the paper.

Repair may add one generation call plus one verification call. Failed repairs
retain the original reviewable draft. Neither latency nor correctness improvements
have yet been measured against institution-provided documents.

## Verification and pilot checks

Completed: 452 backend tests and 115 subtests passed. The frontend production
build, lint and TypeScript checks passed. These checks did not invoke paid AI
providers or change the hosted database.

Offline fixtures cover missing source items, distant keys, conflicting/repeated
keys, changed options, invalid candidates, oversized blocks, mixed PDF routing,
page provenance, original verification context, malformed verifier coverage,
selective repair invariants and insufficient source capacity.

Before relying on this for faculty assessments, test representative permissioned
commerce papers: one typed PDF, a DOCX with tables, a mixed scan/text PDF, and a
long paper with its answer key at the end. Count source questions manually and
compare the receipt, options, keys, currencies, units and review states. Check
review, archive/restore, publish, student attempts and export. Keep source-layout
limitations visible to the pilot faculty. Synthetic tests cannot replace these
human-labeled checks, so the full Phase 3 exit gate remains open until they pass.
