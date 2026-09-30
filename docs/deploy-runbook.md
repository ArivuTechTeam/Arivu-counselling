# Deploy Runbook — quiz-generator-v1

A practical, repeatable guide to getting this app live. The frontend runs on
Vercel; Railway production has two independently deployed backend processes:
the public FastAPI service (`quiz-generator`) and the private durable faculty-job
worker (`quiz-generator-worker`). They share one Supabase project.

> Backend note: there is no `vercel.json`, so the FastAPI backend is **not**
> set up for Vercel serverless. It runs on a host that runs `uvicorn` directly
> (zero adapter work) — **Render** and **Railway** both work; **confirmed live
> on Railway as of 2026-09-26** (verified via the Railway CLI: service
> `quiz-generator`, project `quiz-generator`, environment `production`, domain
> `quiz-generator-production-7461.up.railway.app`). Render remains a valid
> alternative if you're setting this up fresh, but isn't what's deployed today.
> The frontend goes on Vercel.

> **Production service inventory (last verified 2026-09-26):** only
> `quiz-generator` and `quiz-generator-worker` remain. The old daily
> `quiz-generator-retention` service was deleted after migration 59 removed the
> raw AI-log columns it cleaned. Do not recreate that cron for this schema.

## Deployment security gates

### Repository verification baseline

- Keep the frontend on Next.js `15.5.26` or a later patched supported release.
  CI runs `pnpm audit --prod --audit-level high`; a high/critical production
  advisory blocks the repository check.
- CI runs on pull requests, direct pushes to `main`, and manual dispatch. It
  executes backend tests, all isolated database migration harnesses, frontend
  lint/unit/build checks, and Chromium public-access/security-header smoke
  tests.
- The browser suite proves public login/legal routes, unauthenticated dashboard
  redirection, and the response-header baseline. Authenticated student,
  teacher, institution-admin, and super-admin browser journeys still require
  disposable isolated-staging accounts; do not put production credentials in
  GitHub Actions.
- `X-Powered-By` is disabled. JavaScript uses a unique per-request CSP nonce
  with `strict-dynamic`; `script-src` must never include `unsafe-inline` in
  production. Inline style attributes remain allowed because tenant colours
  and charts currently depend on them, but that permission cannot execute
  JavaScript. Nonces force dynamic page rendering, so check Vercel latency and
  invocation usage after deployment.
- Browser auth remains per-tab in `sessionStorage`, which is required by the
  current browser-to-Supabase/browser-to-FastAPI architecture. The nonce-based
  script policy materially reduces the XSS path that could read those tokens.
  Moving tokens to HttpOnly cookies would require a separate backend-for-
  frontend auth redesign; do not claim that storage is HttpOnly today.
- Free-text dashboard searches are sent in authenticated POST JSON bodies, not
  query strings. This keeps names and search phrases out of browser history,
  proxy access logs, referrer URLs, and screenshots. IDs, cursors, statuses,
  and other non-free-text filters may remain in GET query strings.
- GitHub repository rules could not be independently enabled on the current
  private-repository plan. Until required checks are available, treat a green
  `Repository checks` run as a manual merge gate.

Supabase SSL enforcement, network restrictions, Auth CAPTCHA/rate limits, and
backup retention are provider settings, not source-controlled settings. Record
dated dashboard evidence and complete a restore drill before capacity sign-off;
repository tests cannot substitute for those checks.

### AI quiz cost tracking (migration 73)

Apply `migration-73-ai-quiz-cost-workflows.sql` after migration 72 before
deploying the API/frontend cost-run view. It adds private metadata-only
`ai_quiz_workflows`, a nullable log workflow reference and the
service-role-only `ai_quiz_cost_page` aggregate. Deploy both API and worker
to attribute new synchronous and queued runs. Local Docker's API does not
auto-reload: restart it after migration/code changes; restart the worker too
if its profile is enabled. Never rebuild historical runs by timestamp guesses.

Run `node scripts/test-ai-quiz-cost-workflows-db.mjs` for isolated SQL
aggregation, pagination, unknown-price and privilege checks. No live database
or provider billing has been checked by that script. Verify one authorized
generation/import run on staging before rollout, including a fallback/retry,
and confirm its quiz link, stage totals and filter behavior. Costs represent
best-effort recorded usage estimates, not the provider's authoritative invoice.
The operator reported migration 73 applied on 2026-09-26, and a bounded live
queued-generation smoke test recorded one analysis request plus four workflow
requests. Fallback/retry attribution remains an isolated-staging test case.

Do not release until the target Supabase project has been checked directly:

- Enable SSL Enforcement and database Network Restrictions in Supabase.
- Confirm RLS is enabled on every exposed table and apply migration 22.
- Under Authentication > Rate Limits, set the password-reset resend interval
  to at least 20 minutes (no more than three requests per hour per user).
- Enforce no more than five password sign-in attempts per minute per client IP
  at the auth provider/gateway and enable Supabase Auth CAPTCHA for sign-in,
  signup, and password recovery. Supabase's standard password endpoint has its
  own abuse controls, but this repository cannot prove the stricter five/minute
  deployment setting.
- Set backend `APP_DEBUG=false` and use only HTTPS production origins.

These platform settings are not represented by application migrations. Verify
them in the Supabase dashboard for the exact project used by production.

---

## 0. One-time: get the code on GitHub `main`

Merge your work to `main` first (see `docs/merge-workflow.md`).

- **Frontend (Vercel):** builds automatically from GitHub after a PR merges to
  `main`. PR #66 produced merge commit `f5aa0f1`; GitHub's Vercel production
  status reported success on 2026-09-28. That deployment check did not exercise
  an authenticated role journey.
- **Backend (Railway): does NOT auto-deploy from GitHub.** Confirmed
  2026-09-04 via `railway status --json` → the service's `"source"` field is
  `null`. Merging to `main` alone does nothing to the backend — after
  merging, you must manually deploy (see Step 2).

---

## 1. Database (Supabase SQL Editor)

These files live in `migrations/` at the project root. Run these **once, in
order**, top-to-bottom (skip any already applied). Note there is **no
migration 03** — the seed library was removed; `04` drops it.

```
schema.sql
migration-01-enrollments.sql
migration-02-events.sql
migration-04-drop-seed-library.sql
migration-05-practice.sql
migration-06-revised-topics.sql
migration-07-challenges.sql
migration-08-exam-config.sql
migration-09-dev-tenant.sql
migration-10-plan-limits-rls.sql
migration-11-auth-hardening.sql
migration-12-teacher-subjects.sql
migration-13-ai-rate-limits.sql
migration-14-google-oauth-onboarding.sql
migration-15-quiz-extraction.sql
migration-16-chapter-uniqueness.sql
migration-17-document-hash.sql
migration-18-course-subject-uniqueness.sql
migration-19-quiz-extraction-rate-limit.sql
migration-20-teacher-deletion-content-retention.sql
migration-21-fix-google-signup-ambiguous-column.sql
migration-22-browser-data-api-hardening.sql
migration-23-quiz-set-document-link.sql
migration-24-quiz-attempt-limit.sql
migration-25-revision-topic-snapshots.sql
migration-26-daily-exam-session-guards.sql
migration-27-challenge-flow-hardening.sql
migration-28-remove-eager-challenge-session.sql
migration-29-staff-dashboard-performance.sql
migration-30-account-data-deletion.sql
migration-31-chunked-generation-jobs.sql
migration-32-reset-chunked-generation.sql
migration-33-teacher-content-archive.sql
migration-34-document-upload-limit.sql
migration-35-universal-question-grounding.sql
migration-36-super-admin-aggregates.sql
migration-37-student-attempt-snapshots.sql
migration-38-repair-auth-profile-trigger.sql
migration-39-decouple-backend-auth-provisioning.sql
migration-40-fix-admin-auth-insert-order.sql
migration-41-question-review-default.sql
migration-42-api-call-logs.sql
migration-43-faculty-background-jobs.sql
migration-44-challenge-join-codes.sql
migration-45-global-course-catalog.sql
migration-46-seed-global-course-catalog.sql
migration-47-student-level-enrollment.sql
migration-48-tenant-branding-metadata.sql
migration-49-document-figures.sql
migration-50-question-figure-link.sql
migration-51-safe-quiz-reuse.sql
migration-52-batches-assignments.sql
migration-53-signup-batch-membership.sql
migration-54-scoring-policies.sql
migration-55-course-exam-standard.sql
migration-56-paper-profiles.sql
migration-57-tenant-feature-rollout.sql
migration-58-commerce-platform-defaults.sql
migration-59-personal-data-minimization.sql
migration-60-student-contact.sql
migration-61-extended-question-types.sql
migration-62-atomic-student-contact.sql
migration-63-pyq.sql
migration-64-paper-knowledge-base.sql
migration-65-paper-bank-safety.sql
migration-66-paper-attempts.sql
migration-67-atomic-batch-publication.sql
migration-68-teacher-dashboard-aggregates.sql
migration-69-cursor-pagination.sql
migration-70-fair-practice-selection.sql
migration-71-query-plan-indexes.sql
migration-72-atomic-quiz-persistence.sql
migration-73-ai-quiz-cost-workflows.sql
migration-74-role-aware-support.sql
migration-75-atomic-review-and-regeneration.sql
migration-76-examapp-handoff.sql
migration-77-generated-exam-papers.sql
migration-78-handwritten-evaluation-phase-a.sql
migration-79-handwritten-stage1.sql
migration-80-handwritten-rubric.sql
migration-81-handwritten-stage2.sql
migration-82-handwritten-learning.sql
```

Filenames above include the current repository migrations through migration 82.
The operator reported migrations through 74 applied, but this documentation
pass did not independently inspect the target Supabase migration history or all
function privileges. Migrations 63–65 support the paper bank, migration 66 adds
durable private paper attempts, and migration 67 adds atomic
publish-and-batch-assignment. The paper-import worker is unchanged. Before a
new-environment rollout, run a staging paper-import/publish/student-grade drill;
repository tests cannot verify live SQL or provider behavior.
Migration 77 adds tenant paper-format JSON, generated-paper snapshots, the
service-role-only atomic enqueue function, and the `generate_paper` faculty-job
kind. Apply it before deploying the matching API/worker/frontend, then enable
both `PAPER_BANK_ENABLED` and `FACULTY_JOBS_ENABLED` for the rollout.
The batch-publication frontend calls a new `/publish-to-batches` API route so it
fails closed against an older Railway API while Vercel updates after merge;
deploy the API promptly after migration 67 and the main-branch merge.
Migration 68 moves teacher class overview, subject metrics, chapter counts, and
published-quiz summaries into tenant/actor/current-assignment-scoped database
functions. The operator reported it applied on 2026-09-25, but the target
project and live function privileges have not been checked independently.
Confirm that inventory before deploying the A2 backend; otherwise those four
faculty routes will fail if their RPCs do not exist. Run
`scripts/test-teacher-dashboard-aggregates-db.mjs` locally and
`scripts/teacher-dashboard-explain.sql` against staging, then compare the route
contracts and latency before deployment. Migration 68 is additive and does not
delete or rewrite application rows.
Migration 69 adds bounded cursor-page functions and supporting composite
indexes for Release A3. Apply it after migration 68 and before deploying the A3
API; otherwise the student catalogue, student history, and teacher published
monitor routes will fail when their page RPCs are missing. Run
`scripts/test-cursor-pagination-db.mjs` locally, verify function privileges and
query plans against staging, then deploy the API before the frontend response
contract change. The operator reported migration 69 applied on 2026-09-26, but
the target project and live function privileges have not been checked
independently.
Migration 70 adds indexed random-key practice selection for Release A4. Apply it
after migration 69 and before deploying the A4 API; the new selector calls
`select_practice_question_ids_page` and will fail closed if the RPC is missing.
The migration backfills every existing question with a stable sampling key, so
test its duration on production-shaped staging and run it during a low-write
window. During that transaction it temporarily disables only the named
Migration 51 released-question guard, performs the metadata backfill under the
table lock, and re-enables the guard before continuing. Run
`scripts/test-fair-practice-selection-db.mjs` locally and
`scripts/fair-practice-selection-explain.sql` on staging, then smoke-test Smart
Practice, chapter practice, exam type mixes, and batch-restricted challenges.
The operator reported migration 70 applied on 2026-09-26, but the target
project, selector privileges, and indexes have not been independently verified.
Migration 71 adds the two question-first answer indexes validated for Release
A5 and removes two indexes made redundant by the existing answer uniqueness
constraints. Apply it after migration 70 during a low-write window: its regular
index builds allow reads but block writes to each answer table, and a five-second
lock timeout makes it fail safely instead of waiting indefinitely. Run
`scripts/query-plan-indexes-explain.sql` immediately before and after the
migration with the same fake staging tenant/question IDs, save both outputs,
and compare scan type, rows removed, buffers, planning time, and execution time.
Then run the A1 write/load scenario and Supabase performance/security advisors.
The operator reported migration 71 applied on 2026-09-26, but its hosted query
plans, write-load impact, and advisor results have not been independently
verified.
Migration 72 replaces the remaining synchronous per-row generated/imported
quiz writes with one service-role-only transaction. Apply it after migration 71
and before deploying the A6 API and worker together; otherwise generation and
extraction routes that call `persist_generated_quiz` will fail closed. Run
`scripts/test-atomic-quiz-persistence-db.mjs` and
`scripts/test-faculty-jobs-db.mjs` locally, inspect the function privileges,
then smoke-test legacy generation, blueprint generation, extraction, and a
durable lost-response retry on staging. The migration is additive and does not
rewrite existing content. The operator reported migration 72 applied on
2026-09-26. Production schema preflight passed and a bounded queued generation
exercised the persistence RPC; retain an explicit privilege inventory and
lost-response retry drill as staging evidence.
Release A7 adds no migration and authorizes no production load test. After
migration 72 and matching API/worker revisions are verified on isolated
staging, follow `docs/a7-capacity-verification.md`. Its write profile consumes
attempts for 200 or 500 disposable students, so it must never use production
accounts or the production API. Save the read/write JSON reports, both SQL
reports, worker recovery evidence, and infrastructure metrics before capacity
sign-off.

Apply `migration-74-role-aware-support.sql` after migration 73 and before
deploying the role-aware contact API. It preserves existing student requests,
records their role as `student`, renames the owner column to `requester_id`, and
adds the service-role-only `submit_contact_request` function. Its compatibility
wrapper keeps old student submissions working during rollout, but the renamed
owner column means request-history reads require the new API. Deploy the API
immediately after the migration and before the frontend. Run
`node scripts/test-role-aware-support-db.mjs`
before deployment, then smoke-test one student, faculty, and institution-admin
submission plus the super-admin reply/close flow. No worker deployment is
required.

Apply `migration-62-atomic-student-contact.sql` after migration 60 and
before deploying the original contact API that calls `submit_student_contact`;
otherwise student submissions will return a temporary service error. Apply
`migration-61-extended-question-types.sql` after migrations 59 and 60
before enabling `EXTENDED_QUESTION_TYPES_ENABLED`. It adds three objective
question-type enum values. `migration-60-student-contact.sql` creates the private
student feedback and support inbox table; apply it before deploying the contact
API. `migration-59-personal-data-minimization.sql` drops legacy raw AI
prompt/response columns and extends account erasure. The operator reported it
applied on 2026-09-24; a read-only production API probe that day confirmed
`api_call_logs.id` exists and `raw_request`/`raw_response` do not. That probe
does not establish the complete migration history.
`migration-48-tenant-branding-metadata.sql` stores the original institution
logo filename for super-admin display, normalizes the legacy unused color
default, and validates tenant brand colors. Earlier drafts of this runbook named
migrations 31–34 `migration-31-chunked-document-generation.sql`,
`migration-32-reset-chunked-generation-schema.sql`,
`migration-33-document-archive-status.sql`, and
`migration-34-document-upload-limit-30mb.sql`, which do not exist in the repo.)

The repository does not prove which migrations are applied to a deployed
Supabase project. Check the target project before skipping any file. Migration
12 must be applied before deploying backend code that reads `teacher_subjects`.
Migrations 45–46 must be applied before deploying the catalogue picker API.
Migration 13 must be applied before deploying backend code with AI rate limits.
Migration 37 must be applied before deploying backend code that starts student
quiz or practice attempts; it stores the immutable question and scoring snapshot.
Migration 38 must be applied to repair the Supabase Auth profile trigger before
creating students, teachers, or institution administrators. It restores the
required owner and execution privilege and pins a safe empty search path.
Migration 39 must be applied before creating teachers or institution
administrators with the backend. It keeps public student signup in the trigger
but lets the service-role backend create staff profiles with explicit rollback.
Migration 40 must be applied after migration 39 and before deploying backend
code that provisions admin/teacher accounts (2026-09-17): Supabase Auth merges
`app_metadata` onto `auth.users` after the row is already inserted, so the
`AFTER INSERT` trigger from migration 39 alone cannot see the
`provisioned_by_backend` marker at insert time. Migration 40 has the backend
also send a `_backend_provisioning_intent` hint in `user_metadata`, which is
visible at insert time and only ever skips creating a public-signup profile —
it never assigns a role, tenant, or permission; those are still written by the
service-role backend afterward.
Migration 44 must be applied before deploying the friend-challenge join-code
backend. It backfills every existing challenge, makes `(tenant_id, join_code)`
unique, and adds the authenticated `challenge_join` rolling-hour quota. The
application will query `challenges.join_code` immediately after deployment, so
deploying code before this migration will break the Challenge a Friend page.
Migrations 15–19 must be applied in order before deploying quiz extraction;
run the duplicate checks documented in migrations 16 and 18 first.
Migration 22 must be applied to close direct browser access to backend-owned
tables and analytics views. Migration 23 must be applied before deploying the
document log because quiz creation starts writing `quiz_sets.document_id`.
Migration 24 must be applied before deploying the atomic published-quiz attempt
limit. Migration 25 must be applied before deploying revision-topic snapshots;
the API reads and writes `revised_topics.answered_at_revision`. Migration 26
must be applied before deploying the Daily Challenge and Exam Simulator guards;
the API reads and writes `practice_sessions.activity_date` and `active_slot`.
Migration 27 must be applied before deploying the hardened Challenge a Friend
flow. It intentionally stops if duplicate `(challenge_id, student_id)` sessions
already exist; resolve that data first, then rerun it.
Migration 28 removes the obsolete helper that started the challenge creator's
attempt during link creation; apply it after migration 27.
Migration 29 adds tenant-scoped dashboard indexes. Migration 30 is required
before deploying the self-service account-deletion endpoint: it changes the
relevant ownership foreign keys and installs a service-role-only anonymization
function. Test migration 30 with a disposable account and verify its private
Storage object is gone before enabling deletion for production users.
Migration 31 adds chunked document-generation jobs and chunk storage. Migration
32 repairs/recreates that transient chunking schema for databases that received
an earlier version of migration 31; apply it after 31 on an existing database.
Migration 33 adds the `archived` document status used by the content archive.
Migration 34 lowers the Supabase document bucket limit to 30 MiB so storage,
backend validation, and frontend messaging agree.
Migration 35 must be applied before deploying universal question grounding;
generated-question reads and writes use its provenance and verification columns.
Migration 36 must be applied before deploying the scalable super-admin dashboard;
the platform overview, question bank, and AI-monitoring endpoints call its
service-role-only aggregate functions.
Migration 47 must be applied before deploying level-aware student signup. It
materializes operational course levels, backfills existing subjects, and makes
new password and Google signups validate Course + Level atomically.
Migrations 49–50 add the private document-figure catalogue and tenant-safe
question link. Migration 51 adds opt-in immutable publication and safe quiz
duplication. Migration 52 adds level-aware batches and quiz assignments;
migration 53 extends password and Google signup with optional, validated batch
membership. Migration 54 adds scoring policies and atomic per-attempt policy
snapshots. Migration 55 binds an official scoring standard to each course level,
and migration 56 stores one commerce paper profile per course level. Migration
57 introduced per-institution rollout controls. Migration 58 supersedes that
temporary rollout model: every existing and future institution receives the
complete commerce feature set, while Railway variables remain platform-wide
emergency switches. Apply all of 49–58 before enabling their matching
deployment flags. Do not use the
pre-integration `changes-pavyaa` migration numbers: they collided with the
existing catalogue, level-enrollment, and branding migrations.

For a fresh database, `migrations/schema.sql` already includes the final effects
of migrations 31, 33, 34, 35, 37, 39, 40, 47, and 49–58 (verified 2026-09-24 by grepping
`schema.sql` for each migration's distinguishing columns/functions — e.g.
`question_snapshot` from migration 37, and the `_backend_provisioning_intent`/
`provisioned_by_backend` trigger logic from migrations 39–40). The incremental
files remain required for an existing database that predates those changes;
never infer their live applied state solely from the current schema file.
Migration 36 is **not** baked into `schema.sql` (its `platform_*_metrics`
functions are absent there), so it remains required after the baseline schema
for both fresh and existing databases. Migration 38's own ownership/search-path
repair was not independently re-checked against a from-scratch `schema.sql` run
this pass — apply it too unless you've separately confirmed the trigger
function's owner and privileges match what it sets.

---

## 2. Backend → Railway (confirmed) or Render (also supported)

- **Build:** Docker, via `backend/Dockerfile` (confirmed via `railway status
  --json` → `"builder": "DOCKERFILE"`). The Dockerfile runs `pip install
  --no-cache-dir --require-hashes -r requirements.lock` against a pinned,
  hashed `backend/requirements.lock` (verified 2026-09-17 against the current
  `backend/Dockerfile`) — not a bare `requirements.txt` install. Regenerate the
  lock file with the `uv pip compile` command documented at the top of
  `backend/requirements.txt` whenever a direct dependency changes; there is no
  separate dashboard build command.
- **Root directory:** there is **no** dashboard "root directory" setting for
  this service (confirmed `"rootDirectory": null`). Instead, every deploy
  must scope the build to `backend/` at the CLI level:
  `railway up backend --path-as-root --service quiz-generator` (wrapped by
  `scripts/deploy.sh` — use that script rather than a bare `railway up`).
  Running `railway up` from the repo root without `--path-as-root` fails
  ("Railpack could not determine how to build the app").
- **Start command:** leave the Railway dashboard's custom Start Command
  **blank** so it falls back to the Dockerfile's own `CMD`. A leftover custom
  override (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`, predating the
  Dockerfile) caused a production outage on 2026-09-04: for a Docker-built
  service, Railway passes a custom Start Command straight to the container
  without shell expansion, so uvicorn received the literal string `$PORT`
  instead of a number and crash-looped (every request 502'd). Cleared in the
  dashboard, and `backend/Dockerfile`'s `CMD` now uses shell form
  (`CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`) so this
  can't regress even if Railway ever re-applies a plain string command.
- **Python:** 3.12 (set by `FROM python:3.12-slim` in the Dockerfile).

### Required companion Railway service

Durable generation must not run inside the web process. Add this service in
the same Railway project/environment and share
the backend variables with them:

| Service | Root | Dockerfile | Schedule / behavior |
|---|---|---|---|
| `quiz-generator-worker` | `backend` | `Dockerfile.worker` | Always running; no public domain |

Run only one worker initially. The database queue keeps jobs durable across
restarts. Set `RAILWAY_DOCKERFILE_PATH=Dockerfile.worker` on the worker service. Use
Railway shared/reference variables for the existing backend configuration and
secrets rather than copying secret values between services.

The API and worker are separate deployments. `scripts/deploy.sh` updates **only**
`quiz-generator`; it does not update `quiz-generator-worker`. When a backend
change affects worker code, shared job contracts, or settings, deploy the same
verified `main` revision to the worker as a separate, explicitly scoped action.
Confirm the worker uses `Dockerfile.worker`, has no public domain, and is healthy
afterward. Do not mistake an API `/health` response for worker readiness; use
the super-admin `/api/v1/platform/worker-health` check and a small queued-job
smoke test. The obsolete retention cron is not a companion service.

**Observed 2026-09-28:** PR #66 was merged to `main` at `f5aa0f1`; GitHub
repository checks and the matching Vercel production deployment passed. The
current Railway API deployment `ee42e89c-11e9-4685-a8d7-96e2be358ab7`, created
by the later feature-switch redeploy, reported `SUCCESS` with a running instance;
the production `/health` endpoint returned HTTP 200. The worker was deliberately
not redeployed because PR #66 changed neither worker runtime code nor its shared
job contract, so its last observed successful deployment remains `8dfc43bc`.
The operator reported migration 74 applied; that report was not independently
checked against Supabase migration history. PR #66 added no migration. Earlier
Release A verification passed production schema preflight and a live queued
10-question generation through the worker, recording workflow and provider-call
costs. API health does not prove worker readiness, the new authenticated feature
workflows, restart recovery, paper-bank grading, 200/500-user capacity, or backup
restoration.

### Advanced feature master switches

Set the following on the API service. Set `FACULTY_JOBS_ENABLED=true` and
`PAPER_BANK_ENABLED` on the worker too: worker paper extraction reads the latter
at startup. These are deployment-wide emergency switches. With migration 58,
every institution receives the complete commerce feature set automatically;
there is no per-institution feature setup.

| Variable | Recommended production value |
|---|---|
| `FACULTY_JOBS_ENABLED` | `true` after the worker service is running |
| `EXTENDED_QUESTION_TYPES_ENABLED` | `false` until migration 61 and a coordinated API/worker rollout are verified; then enable only if the institution-facing feature is intended |
| `PAPER_BANK_ENABLED` | Code default `false`; observed `true` on both production Railway services 2026-09-25. Before deploying the new paper-attempt API, apply migration 66; verify paper start, incomplete-submit rejection, completed report, and retry behavior. The end-to-end checks remain outstanding. |
| `RATE_LIMIT_PAPER_GRADING_PER_HOUR` | `10` paid descriptive grading attempts per student per rolling hour (requires migration 65) |
| `QUIZ_REUSE_ENABLED` | `true` |
| `REJECTED_PURGE_ENABLED` | Code default `false`; directly observed `true` on the production API 2026-09-28. Permanently deletes rejected questions during publish, so first verify it with disposable draft content. |
| `EXTRACTION_BLUEPRINT_ENABLED` | Code default `false`; directly observed `true` on the production API 2026-09-28. Requires `QUIZ_REUSE_ENABLED=true`; blueprint publication is atomic and can assign the release to a batch when batch features are enabled. |
| `REGENERATE_SET_ENABLED` | Code default `false`; directly observed `true` on the production API 2026-09-28. Enables bounded, draft-only whole-quiz regeneration. Code defaults are 40 questions maximum and 5 concurrent provider calls. |
| `BATCHES_ENABLED` | `true` |
| `SCORING_POLICIES_ENABLED` | `true` |
| `COMMERCE_PACK_ENABLED` | `true` |
| `FIGURE_ATTACH_ENABLED` | `true` |
| `FACULTY_JOBS_POLL_SECONDS` | `3` |
| `FACULTY_WORKER_STALE_SECONDS` | `120` |
| `FIGURE_MAX_PER_DOCUMENT` | `50` |

**Environment variables** (from `backend/.env.example`). The connection and
AI provider variables were confirmed present on the live Railway service as
of 2026-09-04 (existence checked in the dashboard; values themselves were not
re-verified). The policy variables have safe code defaults, but set them
explicitly in Railway so the production policy is visible and easy to edit:

| Var | What |
|---|---|
| `APP_ENV` | set to `production`; rejects localhost/non-HTTPS service origins in production |
| `APP_DEBUG` | must be `false` in production; controls API docs/debug behavior |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | anon public key |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key (server-only, **secret**) |
| `SUPABASE_JWT_SECRET` | verifies legacy HS256 JWTs; ES256/RS256 JWTs are verified with Supabase JWKS |
| `HANDOFF_SHARED_SECRET` | independent random secret of at least 32 bytes, shared only with ExamApp; never reuse the Supabase JWT secret |
| `EXAMAPP_FRONTEND_URL` | ExamApp HTTPS browser origin; the backend appends the handoff path and URL fragment |
| `FRONTEND_ORIGIN` | exact deployed **frontend origin** (scheme + hostname, no path or trailing slash) for CORS |
| `DEEPSEEK_API_KEY` | preferred provider credential for current text stages |
| `DEEPSEEK_MODEL` | text model (default `deepseek-v4-flash`) |
| `DEEPSEEK_THINKING_ENABLED` | keep `false` for predictable structured-output cost/latency unless deliberately testing reasoning |
| `DEEPSEEK_STRUCTURED_MAX_OUTPUT_TOKENS` / `DEEPSEEK_MAX_OUTPUT_TOKENS` | ordinary and large-JSON output budgets |
| `DEEPSEEK_REQUEST_TIMEOUT_SECONDS` | ordinary DeepSeek request timeout |
| `GEMINI_API_KEY` | Gemini vision credential and default text-fallback credential |
| `GEMINI_MODEL` | Gemini model used for vision, fallback, and AI Tutor compatibility route (default `gemini-3.5-flash`) |
| `GEMINI_FALLBACK_MODEL` | retried for a Gemini model-specific 404 before the router continues (default `gemini-3.5-flash`) |
| `GEMINI_BLUEPRINT_MODEL` | retained for direct Gemini structured-call compatibility (default `gemini-3.5-flash-lite`) |
| `AI_FALLBACK_PROVIDER` | text fallback provider (default `gemini`) |
| `TOPIC_ANALYSIS_PROVIDER` | topic/outline and compatibility map-reduce preferred provider (default `deepseek`) |
| `QUIZ_GENERATION_PROVIDER` | standard/blueprint generation preferred provider (default `deepseek`) |
| `TYPED_QUIZ_EXTRACTION_PROVIDER` | typed existing-quiz extraction preferred provider (default `deepseek`) |
| `QUESTION_VERIFICATION_PROVIDER` | grounding-verification preferred provider (default `deepseek`) |
| `QUESTION_REGENERATION_PROVIDER` | review regeneration preferred provider (default `deepseek`) |
| `VISION_EXTRACTION_PROVIDER` | must remain `gemini` until another multimodal adapter exists |
| `REJECTED_PURGE_ENABLED` | API-only publish-time rejected-question purge; code default `false` |
| `EXTRACTION_BLUEPRINT_ENABLED` | API-only extraction-review blueprint and atomic subset publication; code default `false` and requires quiz reuse |
| `REGENERATE_SET_ENABLED` | API-only whole-draft regeneration; code default `false` |
| `REGENERATE_SET_MAX_QUESTIONS` / `REGENERATE_SET_CONCURRENCY` | whole-set safety limits (code defaults `40` / `5`) |
| `RATE_LIMIT_QUIZ_GENERATION_PER_HOUR` | per-user standard quiz generations per rolling hour (default `10`) |
| `RATE_LIMIT_BLUEPRINT_PER_HOUR` | per-user blueprint generations per rolling hour (default `10`) |
| `RATE_LIMIT_TOPIC_EXTRACTION_PER_HOUR` | per-user document-analysis AI calls per rolling hour (default `30`; normal typed-document analysis is one provider call, while explicit compatibility fallback can use multiple calls) |
| `RATE_LIMIT_QUESTION_REGENERATE_PER_HOUR` | per-user question regenerations per rolling hour (default `10`) |
| `RATE_LIMIT_QUESTION_EXPLAIN_PER_HOUR` | per-user question explanations per rolling hour (default `10`) |
| `RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR` | per-user existing-quiz document extractions per rolling hour (default `10`) |
| `RATE_LIMIT_CHALLENGE_JOIN_PER_HOUR` | per-student friend-challenge code lookups per rolling hour (default `30`) |
| `RATE_LIMIT_PAPER_GENERATION_PER_HOUR` | per-teacher generated exam-paper requests per rolling hour (default `10`; requires migration 77 and the faculty worker) |
| `STUDENT_QUIZ_ATTEMPT_LIMIT` | maximum starts per student for the same published quiz variant (default `2`; on Railway redeploy after changing; for local Docker run `docker compose up -d --force-recreate backend` because restarting Docker Desktop preserves the existing container environment) |
| `DAILY_CHALLENGE_TIMEZONE` | IANA timezone used to decide each student's institution-facing Daily Challenge calendar day (default `Asia/Kolkata`) |
| `CHALLENGE_EXPIRY_DAYS` | number of days a new friend challenge accepts new participants (default `30`; existing sessions may still resume) |

Document extraction and durable document analysis add
further tunables — `GEMINI_VISION_TIMEOUT_SECONDS`, `GEMINI_EXTRACTION_MAX_OUTPUT_TOKENS`,
`EXTRACTION_TEXT_CHUNK_CHARS`, `EXTRACTION_CHUNK_CONCURRENCY`,
`GENERATION_MAX_TEXT_CHARS`, `CHUNKING_TRIGGER_CHARS`, `GENERATION_CHUNK_CHARS`,
`GENERATION_CHUNK_OVERLAP_CHARS`, `GENERATION_CHUNK_MIN_CHARS`,
`GENERATION_CHUNK_CONCURRENCY`, `GENERATION_MAP_MAX_OUTPUT_TOKENS`,
`GENERATION_LARGE_REQUEST_TIMEOUT_SECONDS` (default `600` for large background calls),
`GENERATION_PROFILE_MAX_CHARS`, `GENERATION_CHUNK_STUCK_SECONDS` (default `900`,
kept above the large-request timeout) — all read at
startup in `backend/app/lib/config.py` with safe code defaults. See
`backend/.env.example` for the authoritative, commented list and
`docs/current-ai-document-workflow.md` plus
`docs/chunked-generation-architecture.md` for what each one tunes; set them
explicitly in Railway only if the defaults need overriding.

Changing `PAPER_BANK_ENABLED` requires redeploying/restarting both the API and
worker; `app/lib/config.py` reads it at process startup. It is server-only,
not a `NEXT_PUBLIC_*` frontend variable. `PYQ_ENABLED` remains a legacy alias
in code; use `PAPER_BANK_ENABLED` for new configuration.

**Deploying a change (Railway):** merge to `main` first, then run
`scripts/deploy.sh` from `main` (or `railway up backend --path-as-root
--service quiz-generator` directly) — merging alone does not deploy, see
Step 0. This command deploys the API only; assess worker compatibility and
deploy the worker separately when its code or shared job contract changes. On
first-ever setup (fresh Render project, or a from-scratch Railway
project), copy the **backend URL** after the first deploy (e.g.
`https://…onrender.com`); for the current Railway deploy, see the live URL in
Notes/gotchas below.

---

## 3. Frontend → Vercel

- **Root directory:** `frontend`
- **Framework:** Next.js (auto-detected) · Build: `next build`

The institution-admin teacher editor keeps Save/Cancel visible while its
subject list scrolls (`frontend/app/dashboard/institution-admin/users/page.tsx`,
merged in PR #59). The security/test remediation in PR #65 upgraded the
frontend to Next.js `15.5.26` and added the public Playwright smoke suite. PR
#66 then merged the current feature set as `f5aa0f1`; Vercel reported the
production deployment successful on 2026-09-28. Authenticated role journeys
were not rerun after this deployment and remain a manual post-deploy check.

**Environment variables** (from `frontend/.env.local.example`):

| Var | What |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon public key |
| `NEXT_PUBLIC_API_BASE_URL` | the deployed **backend URL** from step 2 |

→ After it deploys, copy the **frontend URL**.

---

## 4. Cross-wire the two

1. Set backend `FRONTEND_ORIGIN` = the Vercel frontend URL → redeploy backend.
2. Set frontend `NEXT_PUBLIC_API_BASE_URL` = the backend URL → redeploy frontend.

(They point at each other; CORS on the backend already allows the configured
origin, plus any `localhost` port for dev.)

Production verification on 2026-09-07: Railway service `quiz-generator` has
`FRONTEND_ORIGIN=https://quiz-generator-drab-nine.vercel.app`. The frontend
returned HTTP 200 and the backend CORS preflight returned that exact value in
`Access-Control-Allow-Origin`. Change it only if the real Vercel production
hostname changes, then restart or redeploy the backend.

---

## 5. Post-deploy smoke test (5 minutes)

1. Open the frontend URL → **/login** loads.
2. Log in as super-admin → Overview + Question Quality load. Open an
   institution and confirm its Course → Level → Subject tree/counts load.
3. Open `/login/<subdomain>` and follow student signup. Confirm institution
   branding and tenant-only Course + Level choices, then create a disposable
   student if the environment permits it.
4. Log in as that student → Dashboard → **Practice & Mock Tests** → **Topic Practice** → take & submit → score shows.
5. **Daily Challenge** → start → streak ticks. **Practice & Mock Tests** → **Mock Exam** → timer counts down.
6. **Leaderboard** shows your course. **Revision** two tabs work.
7. If durable faculty jobs are enabled, check worker health separately and
   submit one small teacher generation/import job; verify it progresses from
   queued to a completed review draft.
8. If `PAPER_BANK_ENABLED=true`, import a small PYQ/MTP/RTP paper as a teacher,
   approve and publish its questions, then use a student in the same subject to
   start a paper attempt. Confirm the taking response hides answer keys and an
   incomplete submission is rejected. Answer every question and submit; only
   then should the report show correct answers. Include an objective and a
   descriptive question; confirm the snapshot exists and any provider failure
   is retryable. Check that another student cannot load the attempt.
9. As an institution admin, open Edit teacher with a long subject list and
   verify Save/Cancel remain visible while the subjects scroll.
10. For native handwritten evaluation Phase A, apply migration 78, set
    `EVALUATION_JOBS_ENABLED=true` on both the API and the dedicated evaluation
    worker, and set `EVALUATION_WORKER_POLL_SECONDS` if the default three-second
    poll is unsuitable. Start the worker with
    `python -m app.services.evaluation_worker` (or the Docker Compose
    `evaluation-jobs` profile). Confirm the private `evaluation-papers` and
    `evaluation-submissions` buckets exist, then test teacher paper upload and
    a same-course/same-level student upload through to `pending_stage1`.
11. For frozen rubric generation, apply migrations 79 and 80 before starting the
    evaluation worker. Set `HANDWRITTEN_RUBRIC_PROVIDER` (default `gemini`).
    Create a paper once with an official suggested answer and once without;
    confirm each automatically queues one `build_rubric` job and reaches
    `rubric_status=ready` with `rubric_source=official` and `ai_derived`,
    respectively. A failed deterministic validation must show a specific
    `rubric_error` and must not persist a candidate rubric.
12. Before enabling native handwritten evaluation Stage 2, apply migration 81
    and configure `RATE_LIMIT_HANDWRITTEN_EVALUATION_PER_HOUR` (default `10`).
    Grouped top-level-question scoring is enabled by default with
    `PER_QUESTION_STAGE2_ENABLED=true` and
    `PER_QUESTION_STAGE2_CONCURRENCY=5`. Unmatched evidence deliberately falls
    back to one whole-paper request so evidence ownership is decided once.
    The ExamApp-matched limits are `DEEPSEEK_PER_QUESTION_MAX_TOKENS=32000`,
    `DEEPSEEK_MAX_TOKENS=80000`, and `DEEPSEEK_THINKING_EFFORT=high` using
    `deepseek-v4-flash`. Fleet-wide DeepSeek calls use leased
    database slots (`DEEPSEEK_MAX_CONCURRENCY=24`, 30-second acquisition wait);
    semaphore storage errors fail open, while a healthy full semaphore retries
    the evaluation job. Stage 2 deliberately uses DeepSeek text response mode
    and persists visible content only—never provider reasoning traces or full
    envelopes. After completion, the student report is read from the persisted
    evaluation and question-evaluation rows; opening a report never re-runs AI.
13. Apply migration 82 before deploying handwritten learning data. Complete one
    non-review evaluation and confirm its mistake rows, revision topic, and
    subject analytics appear. Repeat the same paper and confirm only its latest
    evaluated submission contributes to revision risk. Verify the weak-area API
    computes chapters and category patterns live; the analytics table
    intentionally omits ExamApp's four unused summary fields.

If a page 500s, check the backend logs and that all env vars are set + migrations run.

---

## Notes / gotchas

- **`next build` runs ESLint and fails on errors** — always run `pnpm build`
  locally before deploying, not just `tsc` (tsc misses lint-level errors).
- **Never commit `.env` / `.env.local`** — only the `.example` files are tracked.
- **Heavy routes** (attempt/practice/class-monitor ≈ 640 kB First Load) pull in
  recharts + the PDF renderer. Fine for now; a future win is lazy-loading the PDF
  and chart bundles.
- **Free-tier note:** Render/Railway free tiers sleep on idle (first request is
  slow to wake) — acceptable for a demo, upgrade for real usage.
- **Live backend URL:** `https://quiz-generator-production-7461.up.railway.app`
  (Railway dashboard, verified 2026-09-04). This is where Vercel's
  `NEXT_PUBLIC_API_BASE_URL` should point in production — check the Vercel
  dashboard's env vars, not `frontend/.env.local`, to confirm what's actually
  configured there.
