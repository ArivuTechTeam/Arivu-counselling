# Deploy Runbook — quiz-generator-v1

A practical, repeatable guide to getting this app live. Two deployables:
**frontend (Next.js → Vercel)** and **backend (FastAPI → a host that runs
uvicorn)**, both talking to one **Supabase** project.

> Backend note: there is no `vercel.json`, so the FastAPI backend is **not**
> set up for Vercel serverless. It runs on a host that runs `uvicorn` directly
> (zero adapter work) — **Render** and **Railway** both work; **confirmed live
> on Railway as of 2026-09-04** (verified in the Railway dashboard: service
> `quiz-generator`, project `ExamApp`, environment `production`, domain
> `quiz-generator-production-7461.up.railway.app`). Render remains a valid
> alternative if you're setting this up fresh, but isn't what's deployed today.
> The frontend goes on Vercel.

## Deployment security gates

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

- **Frontend (Vercel):** builds automatically from GitHub via Vercel's
  standard integration (not independently re-verified this session — confirm
  in the Vercel dashboard if unsure).
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
```

(Filenames above verified 2026-09-16 against `migrations/` — earlier drafts of this
runbook named these `migration-31-chunked-document-generation.sql`,
`migration-32-reset-chunked-generation-schema.sql`,
`migration-33-document-archive-status.sql`, and
`migration-34-document-upload-limit-30mb.sql`, which do not exist in the repo.)

The repository does not prove which migrations are applied to a deployed
Supabase project. Check the target project before skipping any file. Migration
12 must be applied before deploying backend code that reads `teacher_subjects`.
Migration 13 must be applied before deploying backend code with AI rate limits.
Migration 37 must be applied before deploying backend code that starts student
quiz or practice attempts; it stores the immutable question and scoring snapshot.
Migration 38 must be applied to repair the Supabase Auth profile trigger before
creating students, teachers, or institution administrators. It restores the
required owner and execution privilege and pins a safe empty search path.
Migration 39 must be applied before creating teachers or institution
administrators with the backend. It keeps public student signup in the trigger
but lets the service-role backend create staff profiles with explicit rollback.
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

For a fresh database, `migrations/schema.sql` already includes the final effects
of migrations 31, 33, 34, and 35. The incremental files remain required for an
existing database that predates those changes; never infer their live applied
state solely from the current schema file. Migration 36 is required after the
baseline schema for both fresh and existing databases.

---

## 2. Backend → Railway (confirmed) or Render (also supported)

- **Build:** Docker, via `backend/Dockerfile` (confirmed via `railway status
  --json` → `"builder": "DOCKERFILE"`). The Dockerfile itself runs `pip
  install -r requirements.txt` — there is no separate dashboard build command.
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
| `FRONTEND_ORIGIN` | exact deployed **frontend origin** (scheme + hostname, no path or trailing slash) for CORS |
| `GEMINI_API_KEY` | quiz generation (primary, if set) |
| `GEMINI_MODEL` | full-tier Gemini model used for generation, blueprint, regeneration, topic extraction, and AI tutor (default `gemini-3.5-flash`; code default in `backend/app/lib/config.py`) |
| `GEMINI_FALLBACK_MODEL` | retried once before falling back to DeepSeek if `GEMINI_MODEL` returns model-not-found (default `gemini-3.5-flash`) |
| `GEMINI_BLUEPRINT_MODEL` | cheap-tier model read by an unused helper (`gemini_json()`) as of 2026-09-15 — see `backend/.env.example` (default `gemini-3.5-flash-lite`) |
| `DEEPSEEK_API_KEY` | quiz generation (fallback) |
| `RATE_LIMIT_QUIZ_GENERATION_PER_HOUR` | per-user standard quiz generations per rolling hour (default `10`) |
| `RATE_LIMIT_BLUEPRINT_PER_HOUR` | per-user blueprint generations per rolling hour (default `10`) |
| `RATE_LIMIT_TOPIC_EXTRACTION_PER_HOUR` | per-user document-analysis AI calls per rolling hour (default `30`; a 300-page document can require 10–11 calls including profiling and consolidation retry) |
| `RATE_LIMIT_QUESTION_REGENERATE_PER_HOUR` | per-user question regenerations per rolling hour (default `10`) |
| `RATE_LIMIT_QUESTION_EXPLAIN_PER_HOUR` | per-user question explanations per rolling hour (default `10`) |
| `RATE_LIMIT_QUIZ_EXTRACTION_PER_HOUR` | per-user existing-quiz document extractions per rolling hour (default `10`) |
| `STUDENT_QUIZ_ATTEMPT_LIMIT` | maximum starts per student for the same published quiz variant (default `2`; on Railway redeploy after changing; for local Docker run `docker compose up -d --force-recreate backend` because restarting Docker Desktop preserves the existing container environment) |
| `DAILY_CHALLENGE_TIMEZONE` | IANA timezone used to decide each student's institution-facing Daily Challenge calendar day (default `Asia/Kolkata`) |
| `CHALLENGE_EXPIRY_DAYS` | number of days a new friend challenge accepts new participants (default `30`; existing sessions may still resume) |

Document extraction and large-document ("chunked" map-reduce) generation add
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
`docs/chunked-generation-architecture.md` for what each one tunes; set them
explicitly in Railway only if the defaults need overriding.

**Deploying a change (Railway):** merge to `main` first, then run
`scripts/deploy.sh` from `main` (or `railway up backend --path-as-root
--service quiz-generator` directly) — merging alone does not deploy, see
Step 0. On first-ever setup (fresh Render project, or a from-scratch Railway
project), copy the **backend URL** after the first deploy (e.g.
`https://…onrender.com`); for the current Railway deploy, see the live URL in
Notes/gotchas below.

---

## 3. Frontend → Vercel

- **Root directory:** `frontend`
- **Framework:** Next.js (auto-detected) · Build: `next build`

**Environment variables** (from `frontend/.env.local.example`):

| Var | What |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | anon public key |
| `NEXT_PUBLIC_DEFAULT_TENANT_ID` | ArivuPro tenant id (signup default) |
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
2. Log in as super-admin → Overview + Question Quality load.
3. Log in as a student → Dashboard → **Smart Quiz** → take & submit → score shows.
4. **Daily Challenge** → start → streak ticks. **Exam Simulator** → timer counts down.
5. **Leaderboard** shows your course. **Revision** two tabs work.

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
