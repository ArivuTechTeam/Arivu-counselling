# Phase 4 rollback

Removed image upload controls, source-figure capture, diagram/chart generation,
image rendering in review/student screens/PDFs, and the media API. Generation
and extraction use the earlier text processing routes again. Existing scanned
question-paper extraction remains available.

Earlier work stays: background jobs and recovery, archive/restore, source
coverage tracking, question repair/verification, and simplified Approve All.
The separate timeout handling changes remain; this rollback does not establish
that every cause of timeouts has been fixed.

## Apply locally

1. Stop the backend and faculty worker before running the SQL.
2. In Supabase SQL Editor, run the entire
   `migrations/migration-44-rollback-phase4-visuals.sql` file. It requires
   migration 41 and works with or without migrations 42/43. It can be rerun.
3. Restart the backend and frontend using your usual commands. Start the worker
   with `powershell -ExecutionPolicy Bypass -File scripts/start-faculty-worker.ps1 -Restart`
   from the project root when `FACULTY_JOBS_ENABLED=true`.
4. Generate and extract a small text-based quiz, approve it, and publish it.
   Check the archive tab and an existing student attempt as well.

The SQL restores the migration-41 job-completion function and removes only
Phase 4 media functions and the visual publication trigger. It does not delete
questions, attempts, documents, assets, or storage objects. Private image
storage remains private. Migrations 42/43 remain as historical records; do not
rerun them after migration 44.

Previously attached images remain stored but are no longer displayed. Review
any existing questions that rely on diagrams before reusing them. No existing
quiz statuses or answers are changed by the rollback.
