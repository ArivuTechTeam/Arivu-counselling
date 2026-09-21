# Phase 2: durable final generation and quiz import

Phase 2 was tested and accepted by the founder. The next source-fidelity increment
is documented in [Phase 3](faculty-pilot-phase-3.md).

This increment adds recoverable background processing for the main faculty blueprint generator (small documents and final generation from completed large-document analysis), new MCQ paper uploads, and document-log re-extraction. It preserves the existing generation prompts, answer validation, review, publication, and student delivery.

## What changes when enabled

- The request returns after submission is saved, rather than waiting for AI completion. Recent tasks on Generate and Extract show queue/running/saving/completed/failed/cancelled state and a link to the finished draft.
- Tasks survive browser refresh and API/worker restarts. Ownership is enforced by institution and teacher. Request parameters, provider output, and lease tokens are not exposed in the task list.
- A UUID identifies a submission intent. Retrying that UUID returns the same task and consumes quota once. An intentionally new quiz uses a new UUID. Import identity includes the file hash and academic selection.
- A separate worker claims one job at a time. Database claims permit at most four live jobs globally and two per institution. These are conservative configurable-in-code pilot limits, not a measured capacity or latency promise.
- Workers heartbeat every 20 seconds with a 120-second lease. Each attempt is bounded to 60 minutes; a process crash or expired lease is recoverable. Provider/transient errors retry up to three total attempts, with delay. Invalid inputs/access fail without provider retry.
- Prepared questions are checkpointed before saving. A crash after that point resumes saving without repeating the model call. A crash before checkpointing may repeat provider work; this is not an exactly-once model-billing guarantee.
- Quiz, variant, questions, links, source filing, generation events, extraction receipt, and completed job result are committed in one transaction. A late/cancelled worker cannot commit. Replaying a successful commit returns its existing result.
- Cancellation prevents committing a future result. An already-running provider request may still finish and incur cost. Cancelling after a successful commit returns the completed task rather than deleting its draft.

Teacher source and subject access are checked on submission, before provider access, and at final commit. Queue tables and RPCs are service-only, with RLS enabled and browser-role privileges explicitly revoked. Existing public APIs still use authenticated teacher authorization.

## Scope boundaries

Large-document **topic analysis** still uses the existing chunk/checkpoint runner; it has not been moved into this queue. The older generic `/generate` API and individual-question regeneration retain their existing paths. This phase improves final quiz generation and import, not every AI operation.

The job ledger records status, attempts, timing, request settings, and provider/result metadata. Full token/cost metering across every provider call and tenant subscription credits remain separate work. Existing per-user hourly quotas are consumed once per submitted logical job; automatic retries are bounded but do not consume additional user credits.

An API endpoint accepting an old synchronous request retains its old behavior. Deploy the updated backend and frontend together; new screens check backend capability before choosing the queue. A queue failure is not silently retried through synchronous generation.

## Activation for the two-institution staging pilot

This feature is **off by default**. No hosted database has been changed by this implementation.

1. Ensure the existing database has the repository's migrations through 40. Take the normal staging backup/restore checkpoint.
2. Apply `migrations/migration-41-faculty-background-jobs.sql` once to staging. This additive migration was generated using the Supabase CLI and moved into the repository's numbered `migrations/` sequence. It is the same SQL previously named `20260919054543_faculty_background_jobs.sql`; if you already applied that file, do not apply it again. Do not run a blanket CLI reset/push against an existing database. A fresh database also needs this new SQL after the existing schema/migrations.
3. In the root Docker `.env`, set `FACULTY_JOBS_ENABLED=true`. For manual Python execution, set the same variable in `backend/.env`.
4. From the repository root, run:

   ```powershell
   docker compose --profile faculty-jobs up -d --build backend faculty-worker frontend
   ```

   For a manual backend setup, run `python -m app.services.faculty_worker` from `backend/` in a separate terminal using the same virtual environment and backend settings. Keep the normal API process running as well.

5. Confirm the worker starts, then submit a small permissioned commerce fixture. Confirm Recent tasks changes from queued to running to completed and opens a normal review draft.
6. Refresh during a second request; return to Generate/Extract and confirm the same task remains visible. Stop/restart only the worker during processing and confirm eventual recovery produces one draft. Test cancellation and two teacher accounts from different institutions.
7. Test both generation paths, typed/scanned imports, and document-log retries. Compare review, publication, PDF export, and student attempts with the existing workflow before enabling the two real pilot institutions.

To run two workers after measuring provider headroom:

```powershell
docker compose --profile faculty-jobs up -d --scale faculty-worker=2
```

The app remains usable with `FACULTY_JOBS_ENABLED=false` and no worker/migration. For rollback after activation, first let active jobs finish or cancel them while the feature remains enabled. Then disable the flag and stop the worker. Retain the additive table/RPCs and completed drafts; do not drop data as a rollback step. Disabling the flag hides Recent tasks and must not strand queued work unnoticed.

## Validation and operational follow-up

- Verification completed: 437 backend tests and 115 subtests passed without paid AI calls. The frontend production build, lint, and TypeScript checks passed. Docker Compose configuration validation and Git whitespace checks also passed.
- `scripts/test-faculty-jobs-db.mjs` executes the migration and real Postgres transactions in isolated PGlite. Its schema fixtures come from this repository. It tests intent/quota replay, lease fencing, cancellation, checkpoint recovery, atomic rollback, retry exhaustion, tenant concurrency, revoked access, and generated item/topic/event persistence. Its quota stub makes consumption observable; existing quota implementation has separate backend tests.
- Reproduce SQL tests from the repository root:

  ```powershell
  npm install --prefix .tmp/pg-test --cache .tmp/npm --no-audit --no-fund --save-exact @electric-sql/pglite@0.3.14
  node scripts/test-faculty-jobs-db.mjs
  ```

- The PGlite transaction checks passed. PGlite does not validate hosted PostgREST schema-cache refresh, separate-process concurrent load, storage behavior, or live provider latency. The Docker daemon was not running during implementation, so a live Docker smoke test remains outstanding. Run staging PostgREST checks and Supabase security/performance advisors after applying the migration.
- Monitor queue age, terminal failures, retry counts, provider cost, and worker restarts. Do not advertise speed or capacity from these functional tests. Saved jobs contain teacher content in their result/checkpoint; include them in the institution's retention/deletion policy. No token-usage or cost savings are claimed yet.
