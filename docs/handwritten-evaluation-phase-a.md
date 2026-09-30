# Native handwritten evaluation — Phase A

Phase A establishes the tenant-safe upload and queue boundary only. It does not
perform OCR, rubric generation, AI evaluation, scoring, mistake extraction or
analytics.

## Data and storage

Migration 78 adds `evaluation_papers`, `evaluation_upload_intents`,
`handwritten_submissions` and `evaluation_jobs`. Evaluation papers are standalone
teacher-authored records. `generated_paper_id` is optional provenance and does
not make generated papers part of the evaluation lifecycle.

The `evaluation-papers` and `evaluation-submissions` buckets are private, accept
PDF/PNG/JPEG objects up to 30 MiB, and are accessed through short-lived signed
URLs. Student uploads use a two-hour upload intent. Finalization downloads the
stored object with backend credentials and verifies its exact byte count and
magic signature; mismatches are marked failed and deleted.

Every academic and ownership relationship has a tenant-aware foreign key.
Student authorization requires an exact enrollment match on tenant, course and
course level. API queries repeat tenant/owner filters even though the service
role is used by the backend.

## Queue contract

Submission creation and evaluation-job insertion happen atomically in
`create_handwritten_submission_job`. Replaying the same verified upload intent
returns the original submission and job instead of inserting duplicates.

The dedicated evaluation worker claims leased `evaluate_submission` jobs. It
rechecks the submission, student, tenant, entitlement, active paper and exact
enrollment before starting. The Phase A stub then marks the job `done` and the
submission `pending_stage1`. That status is an explicit handoff point for Phase
B; it is not an evaluation result.

This queue is intentionally separate from `faculty_jobs`: its owner is a
student, and no teacher-only worker authorization or AI implementation is
shared.

## Operations

- Apply `migration-78-handwritten-evaluation-phase-a.sql` after migration 77.
- Set `EVALUATION_JOBS_ENABLED=true` only after the migration and worker are
  deployed.
- Optionally set `EVALUATION_WORKER_POLL_SECONDS` (default `3`).
- Run `python -m app.services.evaluation_worker`, or start the Docker Compose
  `evaluation-jobs` profile.
- The existing `tenants.handwritten_evaluation_enabled` column is the direct
  tenant entitlement. This feature does not use `effective_feature_flags()`.
