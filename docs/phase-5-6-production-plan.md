# Phase 5 and Phase 6: revised production plan

Date: 22 September 2026. Reviewed branch: `changes-pavyaa`, HEAD `bd3c596`,
including the current uncommitted working tree. Status: proposal, not implementation.

Phase 4 is permanently excluded. Preserve the user's alternative figure work;
do not replace its extraction, attachment, storage, or rendering implementation.
Compatibility of reused questions with existing content is required, not a new
visual-feature project. No application code, migrations, or hosted settings were
changed during this review. Historical test counts are not a verification of
today's changed working tree.

## Current code findings

| Area | Evidence | Consequence for this plan |
| --- | --- | --- |
| Question storage and quiz assembly | `migrations/schema.sql`: questions, quiz variants, links and marks overrides already exist | Extend existing entities; do not create a second independent question bank |
| Faculty library | Teacher routes and screens reviewed do not expose searchable cross-quiz selection or quiz duplication | Build the missing faculty workflow, initially scoped to the teacher's own eligible content |
| Editing | `backend/app/api/questions.py`: edits update the original row; server-read conditional checks exist but no published-release guard in the text edit handler | Safe reuse needs immutable references/copies and client revision checks before duplication ships |
| Source lookup | `backend/app/services/review.py`: regeneration resolves a question's source through a single quiz-link lookup | Simply linking the same mutable question into several quizzes can break source lookup; preserve explicit per-item provenance |
| Publication | `backend/app/api/quiz.py`: reads review state, updates variant totals separately, then publishes | Implement an atomic release boundary with concurrency checks; existing approval checks are not an atomic snapshot |
| Attempts | `backend/app/api/student.py`: snapshots saved at attempt start, with a legacy fallback | Preserve these protections; they do not by themselves freeze the paper for future attempts |
| Saved work | `frontend/components/teacher/blueprint-generator.tsx`: sessionStorage recovery and saved job IDs already exist | Add named server-side presets/drafts, not another browser-only recovery feature; scope browser recovery to user/institution |
| Export and reporting | PDF buttons, published-quiz monitoring and performance routes already exist | Verify compatibility and extend only buyer-required formats; do not rebuild existing reporting |
| Job execution | `faculty_worker.py` uses leases/checkpoints; `generation_jobs.py` also launches in-process threads; async final-generation routes exist | Trace the actual screen/API/config routing and establish one supported deployment contract before claiming timeout resolution |
| Observability | Historical finding: `ai_call_logging.py` captured raw request/response payloads. Current code retains metadata only; migration 59 removes legacy columns. | Keep diagnostics separate from content; provider-side retention and logging-failure behavior still need operational verification. |
| Health and CI | `/health` is liveness only; CI runs backend tests and frontend lint/build | Add dependency/worker readiness, real database migration checks and browser workflow coverage |
| Deletion | `account_deletion.py` removes owned document bytes and invokes the older anonymization function | Reconcile deletion with newer job/log records, ownership-retention rules and existing source assets; verify rather than assume coverage |
| Migration history | Current tree has 41 review default, 42 API logs, 43 faculty jobs, and pending 45/46 figure migrations | Earlier phase documents use different numbers; inventory deployed objects/history before allocating a new migration or replaying old instructions |

## Phase 5: reusable questions and safe quiz authoring

Outcome: a teacher can return, find approved material, assemble a new quiz, and
publish it without uploading or paying for AI again. Existing Generate and
Extract remain available. No mandatory review notes or verification-status gates
are reintroduced.

### 5A. Establish reuse and publication invariants

- Keep current question and quiz entities. Add explicit origin/revision/source
  relationships only where needed. Do not infer the source of a copied question
  from the new quiz's single document field; mixed-source quizzes need item-level
  provenance, including unavailable-source handling.
- Prefer independent question copies for the initial reuse workflow. Editing a
  copy changes only the destination draft; preserve origin IDs for lineage and
  aggregate analytics. Do not share editable rows between quizzes.
- Separate answer/content changes from quiz-specific order and marks overrides.
  Changed content requires approval again; unchanged copies may retain the
  original approval evidence without falsely recording a new teacher approval.
  Final release is always deliberate.
- Make publication an atomic operation: validate ownership, subject access,
  question revisions, review state, membership and totals, then commit the
  released content together. Reject a concurrent change with an actionable
  conflict response. The teacher should not have to enter a review note.
- Freeze published content for subsequent attempts and export. A later edit
  creates a new draft/copy; it cannot change an active or historical release.
  Preserve existing snapshots and legacy attempt readability. Do not invent
  missing historical snapshots or silently rewrite results during migration.
- Use explicit expected revisions for edits/reordering; existing conditional
  server-read comparisons alone cannot detect every stale browser form.
- Reuse existing figure references through their current authorized interface.
  Validate retention/access compatibility without rebuilding visual processing.
  Never silently discard existing content when copying a question.

Gate: editing a reused question leaves the source quiz, active attempts, results,
and released PDF unchanged. Concurrent edit/publish cannot produce a mixed paper.

### 5B. Deliver My Questions and Create from library

- Server-side search and pagination, with subject, chapter/topic, type, difficulty
  and review-status filters. Default selection to approved questions. Show
  missing classifications honestly rather than guessing a subject/topic.
- Scope reads and writes to institution, teacher ownership, and current subject
  permission. Student APIs never expose answers through this library. Department
  sharing, teacher-to-teacher transfer and institution banks are deferred until
  ownership policy is agreed.
- Let teachers select questions, see count/marks, reorder, remove and adjust
  quiz-specific marks, then save a draft. Start with one subject per quiz;
  multiple chapters within that subject are supported explicitly.
- Offer Duplicate quiz as a new draft using the same copy service. Never copy
  publication state, attempts, scores or audience access as new historical facts.
- Commit draft, variants, copied questions and links in one transaction. Use an
  idempotency key so double-clicks and lost responses produce one draft. Bound
  batch sizes and use indexed queries; test query plans on a realistic fixture.
- Show a preview, source reference where available, and duplicate-in-selection
  notice. Do not automatically merge distinct imported occurrences based on text.
- Keep draft/archived-only questions out of student practice. Reuse frequency
  must not unintentionally overweight copied questions in practice selection.

Gate: search -> select -> save -> approve -> publish -> attempt -> export works
without an AI call. Wrong-owner IDs, cross-tenant IDs, stale selections, replay,
partial-save failures and source deletion have explicit tests.

### 5C. Add named presets and durable drafts

- Save generation type counts, difficulty, cognitive level and optional topic
  allocation as named teacher-owned presets. Record a schema version and validate
  all loaded fields through the same backend rules as a new request.
- Separate a reusable preset from a document-bound brief and from a running job.
  Applying a preset to another document requires mapping topic choices to that
  document's current analysis. Never reuse unrelated source IDs or page ranges.
- Persist draft authoring state server-side for cross-device use; keep browser
  storage only as a recovery aid, scoped by tenant/user and cleared on logout or
  account switch. Explain conflicts rather than overwriting a newer saved draft.
- Preset selection fills the form; it does not start paid generation automatically.

Gate: a teacher resumes on another device, and revoked/deleted source access or
changed topic analysis produces a clear remapping step rather than a wrong quiz.

### 5D. Verify existing export and measure actual value

- Export the exact selected release, order, numbering, answers and marks. Test
  existing question types, notation, long options and existing attachments through
  their current implementation. Add DOCX/LMS export only for a confirmed buyer need.
- Record created-from-library, duplicate, content-edit and publication lineage
  separately from generated-question counts. Copies are not new AI generations.
- Define usage as distinct publication uses, active authoring time separately from
  waiting, and cost per approved usable question with retries included. Do not
  claim exact savings from click events or incomplete provider logs.
- Run two observed tasks per pilot teacher: initial creation and repeat creation.
  Proposed acceptance target: median active faculty time at least 30% lower than
  their measured baseline with no decrease in expert-reviewed correctness. Report
  sample size; this is a target, not an existing result.

## Phase 6: controlled paid-pilot operations

Outcome: one coaching institute and one college can operate with documented
service limits, reliable recovery and accountable support. Begin essential
reliability/privacy work alongside Phase 5; do not postpone it until all features
are finished. This is not a claim of readiness for high-stakes examinations.

### 6A. Reproducible deployment and schema reconciliation

- Inventory the actual database objects, applied migration history and checksums
  against the merged tree. Resolve renumbered migrations in staging; do not rerun
  an old numbered SQL file merely because an earlier document mentions it.
- Specify matching frontend/API/worker versions, feature flags and deployment
  order. Test an upgrade from a representative existing database as well as a
  fresh supported installation. Reconcile requirements.txt/lockfile use across
  development, CI and deployment.
- Extend existing CI with isolated database migrations, authorization/transaction
  tests, and browser smoke tests for generate/import/reuse/review/archive/student
  attempt/export. Keep live provider evaluations separate from deterministic CI.
- Add pilot-scoped enable/disable controls. Rollback must preserve drafts,
  completed releases, attempts and queued work; document draining/cancellation.

### 6B. Resolve and prove job reliability

- Trace each active route: upload, topic analysis, final generation, extraction,
  regeneration and their frontend polling behavior. Reproduce the user's timeout
  with request/job correlation before declaring it fixed.
- Choose the existing supported worker path for final generation/import; document
  any remaining in-process analysis execution and recovery. Avoid a third queue.
- Add worker heartbeat/queue-age monitoring and readiness distinct from API
  liveness. Supervise workers with restart and graceful-shutdown behavior.
- Test browser refresh, API/worker restart, provider 429/5xx/timeouts, malformed
  output, database interruption, cancellation, expired leases and checkpoint reuse.
  Prove one logical submission saves one quiz and no stale worker overwrites it.
- Use a declared workload: document sizes/routes, question counts, simultaneous
  teachers and students. Proposed queue acknowledgement target: p95 <= 2 seconds
  after upload for the agreed test load. Measure total processing separately by
  route; negotiate limits from evidence, not institution count alone.

### 6C. Privacy, permissions and recovery

- Test API and database access as two teachers, two institutions, a student and
  an administrator, including library search, copied source links, exports, jobs
  and logs. Test revoked subject access during an in-flight operation.
- Minimize raw AI payload logging by default; define opt-in diagnostic access,
  redaction, retention and cleanup for request/response bodies. Inspect existing
  stored payloads and document who can access them. Keep usage metadata distinct
  from source content and never expose API credentials in diagnostics.
- Extend deletion/retention coverage to jobs, checkpoints, logs, copies and
  source assets using the existing alternative implementation. Distinguish
  personal-account erasure from institution-owned academic record retention.
  Make retries safe after partial storage or database deletion failures.
- Run an isolated restore drill covering database records AND storage objects;
  confirm authentication, question/source links, attempts and grades afterward.
  Agree recovery time and acceptable data-loss targets with the two buyers,
  record measured results, and assign a backup/restore owner.

### 6D. Usage, limits and support

- Extend the current AI-call dashboard with job correlation, queue age, failure
  stage, retry/fallback counts and retention-aware diagnostics. Preserve current
  provider selection; this phase is not another prompt/provider rewrite.
- If charging by usage, introduce durable usage records and reconcile them with
  provider reports. Best-effort daemon-thread logs and price-table estimates
  must not become the sole basis for charging customers. Missing usage remains
  unknown, not zero.
- Enforce stated institution concurrency/usage limits before paid work starts.
  Document how retries, failed jobs and cancelled requests affect entitlements.
- Define onboarding and offboarding, supported inputs, support owner/contact,
  incident escalation, maintenance communication, and a source/answer correction
  procedure. Test configuration rather than assuming old deployment notes remain
  accurate.

### 6E. Controlled release gate

- Onboard one coaching institute and one college, with representative permissioned
  commerce documents and named faculty contacts. Expand subjects only after
  evaluating their documents and grading requirements.
- Observe repeated end-to-end usage, including reuse, support incidents and
  restore/recovery. Record correctness, missing items, faculty time and costs.
- Release only with evidence of tenant isolation, upgrade/rollback success,
  recovery within agreed targets, job failure recovery and usable exported papers.
  A successful build or synthetic test suite alone is not the production gate.
- Keep a signed-off acceptance record listing evidence, remaining limits, owners
  and rollback steps. Expand beyond two institutions only after this gate passes.

## Recommended delivery order

1. Confirm the merged baseline and finish the reliability/schema inventory (6A/6B).
2. Establish safe copying and atomic release, then ship library/duplicate together
   (5A/5B). A read-only library preview may ship earlier; mutable shared reuse may not.
3. Add presets and durable drafts (5C), then measure reuse/export (5D).
4. Complete recovery, privacy and support gates (6C/6D), then the two-customer
   acceptance period (6E). No fixed delivery estimate until the baseline and
   concurrency/retention requirements are agreed.

No rebuild of Phase 4, new AI diagram system, automatic publication, mandatory
approval notes, LMS replacement, proctoring or broad department-sharing rollout
is included. Implementation requires the user's next authorization.
