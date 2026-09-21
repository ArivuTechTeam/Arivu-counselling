# Faculty pilot: implementation and validation tracker

Pilot: one commerce coaching institute and one non-engineering college. Commerce is the first benchmark domain; the implementation retains all existing question types and does not hard-code a department. Competitive-exam institutes are another intended customer category. Their use of existing MCQ documents is a discovery hypothesis, not a confirmed universal workflow.

The earlier 45–75 engineer-day estimate covered the entire roadmap, including media, reuse, and operational readiness. It is not a prerequisite wait before a two-institution pilot. Re-estimate after each tested increment and after reviewing actual pilot documents.

## First implementation increment

- Unchanged saves preserve verification/review state and do not count as content edits in analytics.
- Real content edits invalidate prior verification and require renewed individual review.
- Bulk approval includes verified pending questions only; the UI displays the server's actual count.
- Individual approval of uncertain items is allowed without a mandatory note. The original verification outcome remains visible; teacher approval is a separate decision. Structurally invalid answers cannot be overridden.
- Reviewer and timestamp are persisted with approval. An optional resolution note is retained with the question when supplied. Analytics events are additional best-effort instrumentation.
- Conditional updates reject content changes occurring between the server's read and write. This does not yet provide full version history or detect every stale browser view.
- Import merging preserves occurrences, including repeated stems and identical questions from different sections. Without reliable source identifiers, deleting based on wording risks losing valid questions.
- New imports persist an import receipt in the existing extraction job. Review shows imported/skipped counts and previews/reasons for invalid candidates after reload. These are model-candidate counts, not verified source-document counts.
- Review loads extraction confidence and flags low confidence without claiming a probability of correctness.
- Shared practice selectors exclude questions linked only to draft/archived quizzes. Approved standalone bank items retain their existing availability. Published questions are still practice-eligible: explicit exam-only/embargo controls remain outstanding.

No new dependencies or schema migrations are required for this increment. Deploy the backend and frontend together. No existing question rows are rewritten automatically. Earlier extraction jobs have no saved receipt and cannot be given a trustworthy historical reconciliation retrospectively.

## Baseline and faculty acceptance work

Use [faculty-pilot-baseline.csv](faculty-pilot-baseline.csv) for observations. Keep real student names, institution secrets, and copyrighted source files outside committed fixtures. Use permissioned or synthetic examples in tests.

For each pilot, collect representative commerce MCQ papers and source notes: clean DOCX, typed PDF, a table/numerical problem, repeated stems, a separate final-page key, and the hardest commonly used scanned/diagram-bearing file. Ask faculty to enumerate source questions and key answers before testing.

Observe the same faculty creating a usable assessment using their normal workflow and the product. Record active checking/editing time separately from waiting. Repeat on a second document. Compare answer accuracy and usable questions alongside time; faster unchecked drafts are not a productivity gain.

Suggested metric: median percentage time saved = median of each task's `(manual_active_minutes - product_active_minutes) / manual_active_minutes`, excluding missing/zero manual baselines. Report sample size and workflow separately. Include import omissions and support assistance in the result.

## Smoke checks before pilot deployment

1. Open an unsupported generated question, save without changing it, and confirm it stays unsupported but can be approved individually after the warning is reviewed.
2. Optionally record a meaningful source-check note on a structurally valid item. Approve it; reload and confirm the note and original verification outcome remain visible.
3. Bulk approve a mixed batch. Only verified pending items change; ambiguous, unsupported, manually edited, and rejected items remain for individual action.
4. Import a fixture with repeated stems and one invalid answer. Confirm both valid occurrences survive and the invalid candidate appears in the receipt after reload.
5. Confirm an approved draft-quiz question is absent from new practice/challenge selections. Publish its parent and confirm it becomes available. Existing attempt snapshots must remain unchanged.
6. Repeat access checks as another teacher and another institution. Test JSON answer types, including multi-select and numerical answers, against staging PostgREST.

Automated tests use local in-memory service doubles and mocked provider output. They do not establish live model quality, production database behavior, or measured faculty productivity. Staging browser/DB checks and faculty acceptance remain necessary.

The pre-change baseline passed 406 backend tests and 115 subtests. The final backend suite passed **426 tests and 115 subtests**. Frontend TypeScript checking, lint, and the production build passed after the implementation. New regressions cover unchanged saves (including null/empty explanations), explicit review notes through HTTP, invalid answer rejection, concurrent updates, import reconciliation after reload, bulk approval ownership filters, and both practice selection modes.

## Remaining roadmap

Phase 0 is not fully complete until permissioned customer documents, actual workload, and measured faculty baselines are available. Phase 1 still needs durable item/version-level resolution history and explicit practice/exam release eligibility; this increment supplies narrower protections without a database migration. Actual edits run answer-shape checks, but do not yet rerun source/AI verification automatically.

The next increment is now implemented behind a rollout switch: see [Phase 2 background processing](faculty-pilot-phase-2.md) for supported paths, activation, and validation limits. Answer-key matching, formatting/page coverage, selective candidate repair, and required pictures/diagrams/graphs remain ahead. Shared reuse/export and paid-pilot operational drills follow. Each phase needs its own tests and rollout evidence; this increment is not a claim that the full roadmap is complete.
