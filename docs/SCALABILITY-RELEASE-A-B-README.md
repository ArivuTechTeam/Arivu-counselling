# Scalability Release A and B Implementation README

**Status:** Release A1 through A3 are implemented on their feature branches.
The operator reported migrations 68 and 69 applied; the target project has not
been independently inspected. Release A4 is implemented locally on
`release-a-a4-fair-practice-selection`. Production-shaped staging and
capacity sign-off remain pending.

**Prepared:** 25 September 2026

**Initial planning horizon:** first 10 institutions

**Owners:** ArivuPro engineering team

**Purpose:** preserve the evidence, decisions, implementation sequence, and
acceptance criteria for making the quiz platform reliable at multi-institution
scale.

---

## 1. Executive decision

The existing relational database is not fundamentally wrong. PostgreSQL can
store millions of quiz, question, attempt, and answer rows when access paths are
bounded and indexed correctly. The present Course → Level → Subject → Chapter
model and tenant-owned operational tables are a sound foundation.

The application is **not yet proven for the full workload described in this
document**. Several current API paths retrieve every matching row and aggregate
inside Python; student catalogue reads are unbounded; large-bank practice
selection examines only a bounded leading pool; full question snapshots are
duplicated per attempt; and the existing concurrency test does not exercise a
real Supabase database or AI provider.

The decision is therefore:

1. Keep one shared PostgreSQL/Supabase database for the initial 10
   institutions.
2. Complete **Release A** before onboarding all 10 institutions.
3. Complete the applicable parts of **Release B** before formal-exam scale or
   millions of attempts make snapshot migration expensive.
4. Do not introduce microservices, sharding, Kafka, a data warehouse, or one
   database per institution without measured evidence.
5. Replace planning assumptions with production measurements after the first
   one to three months of real institutional use.

This document is a plan, not proof that production is ready. Repository files
do not prove which migrations are applied, how Railway is currently sized, or
how the live Supabase project behaves under load.

---

## 2. Why this work is required

### 2.1 Example content volume

The example course has five subjects containing:

```text
20 + 15 + 10 + 15 + 16 = 76 chapters
```

At 300 quizzes per chapter:

```text
76 chapters × 300 quizzes = 22,800 quiz sets per course
```

At five courses per institution and ten institutions:

```text
22,800 × 5 × 10 = 1,140,000 quiz sets
```

If each quiz contains ten questions, that produces approximately:

| Table or relationship | Approximate rows |
|---|---:|
| `quiz_sets` | 1,140,000 |
| `quiz_variants`, assuming one variant per set | 1,140,000 |
| `questions` | 11,400,000 |
| `quiz_variant_questions` | 11,400,000 |

The complete theoretical envelope is larger when every institution has five
courses, every course has three levels, every level has five subjects, every
subject has twenty chapters, and every chapter reaches 300 quizzes:

```text
10 × 5 × 3 × 5 × 20 × 300 = 4,500,000 quiz sets
```

At ten questions per quiz, that is 45 million question rows and 45 million
quiz-question links. This is an upper-bound stress scenario, not the expected
launch dataset.

### 2.2 Student activity grows faster than course structure

The small Course/Level/Subject/Chapter tables are not the main storage risk.
Attempts and answers multiply with student activity:

```text
10,000 students
× 100 attempts per student per year
× 10 answers per attempt
= 10,000,000 answer rows per year
```

If the platform reaches 50,000 students under the same behavior, that becomes
50 million answer rows per year. Full JSON question snapshots stored on every
attempt may consume more storage than the normalized quiz definitions.

### 2.3 Storage is not the only bottleneck

At large scale the platform must also handle:

- student catalogue payloads and browser rendering;
- simultaneous attempt starts, autosaves, and submissions;
- teacher dashboard aggregation across many quizzes and attempts;
- fair random selection from a large approved question bank;
- faculty AI-job queueing and provider limits;
- private document and figure storage;
- human review of generated questions;
- tenant isolation on every service-role query;
- backups, recovery, monitoring, and capacity alerts.

Generating hundreds of quizzes per chapter also creates a content-management
problem. Generated candidates, reviewed questions, published releases, assigned
assessments, and archived history must not appear as one flat catalogue.

---

## 3. Current architecture confirmed from the repository

### 3.1 Foundations that should be retained

- One shared Supabase/PostgreSQL database serves multiple institutions.
- Tenant-owned operational tables carry `tenant_id`.
- `profiles` is the authoritative application identity and role record linked
  one-to-one to Supabase Auth.
- The operational academic hierarchy is Course → Level → Subject → Chapter →
  Topic.
- `enrollments` grants student Course + Level access.
- `teacher_subjects` grants explicit teacher-to-subject access.
- Quiz content is normalized as `quiz_sets` → `quiz_variants` →
  `quiz_variant_questions` → `questions`.
- Documents and extracted figures live in private Supabase Storage; database
  rows retain paths and metadata.
- Standard grading is deterministic.
- AI-generated questions require teacher review before student delivery.
- Durable faculty work uses a database-backed queue and a separate Railway
  worker.
- Student attempts freeze question/scoring state for fairness and
  reproducibility.
- An append-only `events` table and event logging already exist; the older
  scalability draft that called instrumentation entirely missing is historical.
- Migration 29 already provides several staff-dashboard compound indexes.
- Migration 36 already defines database-side super-admin aggregate functions,
  although it is not folded into `schema.sql` and its live application state
  must be checked separately.

### 3.2 Current limitations confirmed from code

| Area | Current behavior | Why it becomes a problem |
|---|---|---|
| Teacher overview | Retrieves all matching sets, variants, attempts, and question links, then aggregates in Python | Memory, network, and latency grow with the complete teacher history |
| Teacher subject metrics | Retrieves all relevant questions, quizzes, variants, and attempts before grouping in Python | Large teachers/subjects cause repeated paged reads and application work |
| Published quiz monitor | Returns every published quiz owned by the teacher with computed metrics | An institution may have thousands of published records |
| Student quiz catalogue | Retrieves every published quiz available through enrolled subjects/batches | Large payload and unusable browser list |
| Chapter counts | Retrieves quiz/question rows merely to count them | The database should perform grouped counts |
| Practice selector | Reads at most 2,000 eligible questions and shuffles in Python | Large banks can be biased toward the returned subset |
| Attempt snapshots | Copies complete question data into each attempt | Correct but storage-heavy at millions of attempts |
| Some generation paths | Insert questions and link rows one at a time | Excess database/Data API round trips |
| API runtime | One Uvicorn process per Railway API replica | Capacity is unknown until measured; scaling replicas multiplies upstream load |
| Faculty worker | One job at a time per worker process | A single worker creates a queue during faculty bursts |
| Existing load test | Uses 15 concurrent requests with generation mocked | Does not measure Supabase, Railway, Storage, or provider capacity |

### 3.3 How one subject is represented

PostgreSQL does not allocate one separate database area per subject. Rows from
many institutions and subjects coexist in shared tables and are found using
tenant, subject, chapter, owner, status, and time indexes.

A subject cannot independently become “full.” The project reaches limits when
the overall database, indexes, storage bucket, compute, I/O, connections, or
application paths reach their provisioned capacity. Correct tenant-qualified
compound indexes prevent every request from scanning unrelated institutions.

---

## 4. Provisional capacity target for the first launch

Because the product has not launched, these numbers are engineering test
targets rather than customer forecasts.

| Measurement | Release A target |
|---|---:|
| Institutions | 10 |
| Registered students per institution | 1,000 |
| Total registered students | 10,000 |
| Faculty per institution | 50 |
| Courses per institution | Up to 5 |
| Levels per course | Up to 3 |
| Subjects per level | Up to 5 |
| Chapters per subject | Up to 20 |
| Reviewed/published quizzes per chapter | Up to 50 |
| Generated or archived quiz candidates per chapter | Up to 300 |
| Questions per quiz | 10–20 |
| Student attempts per year | 1 million |
| Answer rows per year | 10–20 million |
| Expected simultaneous students | 200 |
| Stress-test simultaneous students | 500 |
| Faculty jobs running at once | Start with the existing global cap of 4 |
| Additional faculty jobs | Durable queue with observable waiting time |

The distinction between generated and published content is mandatory. The
database may retain up to 300 generated/archived candidates per chapter, but
students should normally see only a smaller reviewed, published, and assigned
set.

### 4.1 Proposed service objectives

These are acceptance targets for staging tests, not claims about current
production:

- ordinary API reads: p95 below 500 ms;
- student quiz catalogue: p95 below 800 ms;
- attempt start, autosave, and submit: p95 below 1.5 seconds;
- teacher dashboards: p95 below 2 seconds;
- error rate under expected load: below 1 percent;
- zero cross-tenant responses;
- no lost student submission after an acknowledged success;
- worker restart does not lose a queued or leased job;
- faculty queue pressure does not make the public API unavailable.

“p95 below 500 ms” means at least 95 percent of measured requests complete in
500 milliseconds or less.

---

## 5. Release A — launch hardening for 10 institutions

**Goal:** remove the known unbounded data paths, establish measurable capacity,
and prove the most important student/faculty workflows at the provisional
target.

**Estimated time:** 4–6 weeks for two developers working full-time. Part-time
work increases calendar time. Estimates include implementation, review,
regression testing, and a reasonable correction buffer.

### A1. Production-shaped staging dataset and observability

**Implementation status (25 September 2026):** the repository tooling and
local verification for A1 are complete. No hosted staging or production system
was changed. A real staging seed and measured capacity run remain an operational
sign-off step because they require an isolated staging database, staging role
tokens, and provider dashboards. This is intentionally not described as proof
that production supports the target yet.

**Why**

Capacity cannot be decided from institution count alone. The team needs real
measurements for rows, request concurrency, query time, memory, I/O, queue age,
and error rate.

**How**

1. Build a repeatable staging data generator with tenant-safe fake data.
2. Seed the 10-institution Release A envelope without personal information.
3. Capture p50, p95, and p99 latency by route.
4. Inspect top queries through Supabase/Postgres query statistics.
5. Record table and index sizes, live/dead tuples, and autovacuum/analyze state.
6. Monitor Railway API/worker CPU and memory plus faculty queue age.
7. Define alert thresholds and a repeatable capacity report template.

**Likely files**

- new scripts under `backend/scripts/` for safe data generation and load tests;
- `backend/tests/` for deterministic capacity-shape tests;
- `backend/app/main.py` or a focused metrics helper for safe route timing;
- `backend/app/services/worker_health.py` for queue-health coverage;
- `docs/deploy-runbook.md` when operational monitoring steps are implemented.

**Acceptance criteria**

- The seed can create multiple tenants without reusing production identifiers.
- A test report contains row counts, route latency, error rate, database load,
  and worker queue behavior.
- The test can be repeated after every optimization.
- No real user data, tokens, prompts, answers, or secrets are logged.

#### A1 implementation delivered

| Artifact | Purpose | Safety boundary |
|---|---|---|
| `backend/scripts/capacity_baseline.py` | Runs bounded concurrent API reads and records throughput, status counts, error rate, p50, p95, p99, maximum latency, and application time from `Server-Timing` | Only `GET`/`HEAD`; local by default; an exact remote staging host must be confirmed; production host can be explicitly denied; tokens and bodies are never stored |
| `backend/scripts/capacity_scenario.json` | Defines real public, student, teacher, institution-admin, super-admin, and worker-health read routes plus their provisional p95 objectives | Authentication comes from role-specific environment variables, not committed files |
| `scripts/capacity-seed.sql` | Creates deterministic fake tenants and the Course → Level → Subject → Chapter → Quiz → Variant → Question structure | Refuses to run until `STAGING_ONLY` is explicitly confirmed; dimensions cannot exceed the reviewed Release A envelope; contains no users or personal data; is not a migration |
| `scripts/capacity-database-report.sql` | Reports database size, connections, live/dead tuple estimates, analyze/vacuum state, table/index sizes, index scans, and faculty queue age | Starts a read-only transaction and changes no application rows |
| `scripts/test-capacity-seed-db.mjs` | Executes the smoke seed twice in isolated in-memory PostgreSQL and verifies exact counts, idempotency, and tenant-consistent links | Uses no network, hosted database, credentials, or real users |
| `backend/tests/test_capacity_baseline.py` | Verifies scenario validation, read-only enforcement, remote-target protection, percentile calculations, safe report content, and SQL guards | Runs locally without external services |

The API already emits a safe route-template completion log and a
`Server-Timing: app;dur=...` header in `backend/app/main.py`. A1 reuses this
instrumentation instead of adding a second timing mechanism.

#### A1 target shape and safe seed procedure

The default SQL profile is deliberately small: two fake tenants, one course
per tenant, one level per course, two subjects per level, two chapters per
subject, five quizzes per chapter, and five questions per quiz. It is the smoke
test for correctness, not a capacity claim.

The reviewed maximum settings in the SQL file model 10 institutions, five
courses per institution, three levels per course, five subjects per level,
twenty chapters per subject, 50 published plus 250 archived quiz candidates per
chapter, and ten questions per quiz. That maximum produces 4.5 million quiz
sets and 45 million questions. It must not be run until staging storage and
cost are reviewed. Start with 1%, then 10%, then the expected launch shape; do
not jump directly to the theoretical maximum.

The content seed intentionally does not fabricate Supabase Auth rows, student
attempts, answers, documents, prompts, or uploaded files. Auth records must be
created through supported Supabase Auth paths, and write-workflow load requires
disposable staging student accounts plus an explicit cleanup plan. Reusing one
role token can measure route/database saturation, but it does not prove
per-user attempt isolation for 10,000 distinct students.

Run the isolated checks first:

```bash
node scripts/test-capacity-seed-db.mjs
cd backend
venv/bin/python -m pytest tests/test_capacity_baseline.py tests/test_quiz_generation_load.py -q
```

For an authorized staging seed, connect only to the isolated staging database,
set the confirmation and desired dimensions shown at the top of
`scripts/capacity-seed.sql`, then execute that file. Never add it to the normal
migration sequence. Its deterministic identifiers make a repeated run with
the same seed label idempotent.

#### A1 API baseline procedure

Role tokens must exist only in the operator's shell environment:

```bash
export CAPACITY_STUDENT_TOKEN='<staging token>'
export CAPACITY_TEACHER_TOKEN='<staging token>'
export CAPACITY_INSTITUTION_ADMIN_TOKEN='<staging token>'
export CAPACITY_SUPER_ADMIN_TOKEN='<staging token>'
export CAPACITY_PRODUCTION_HOST='api.example.com'
```

Run a small staging probe before increasing concurrency:

```bash
cd backend
venv/bin/python scripts/capacity_baseline.py \
  --base-url https://staging-api.example.com \
  --allow-remote-staging \
  --confirm-host staging-api.example.com \
  --role public --role student --role teacher \
  --role institution_admin --role super_admin \
  --rounds 10 --concurrency 10 \
  --output ../.tmp/capacity-a1-c10.json
```

Repeat at 25, 50, 100, 200, and finally 500 concurrent in-flight requests only
while error rate, database pressure, and provider resources remain healthy.
Concurrent requests are intentionally more aggressive than “logged-in users”
because ordinary users pause between actions. They are not equivalent metrics,
so record both the test concurrency and the expected real-user interpretation.

After every run, execute `scripts/capacity-database-report.sql` read-only on
staging, save Railway API/worker CPU and memory observations, and record the
Supabase Query Performance view. `pg_stat_statements` text is not exported by
the repository script because SQL text can contain identifiers or values that
should not be committed.

#### A1 alert starting points

These are provisional staging/production alert thresholds and must be revised
using pilot evidence:

| Signal | Warning | Critical/action |
|---|---:|---:|
| API error rate over 5 minutes | 0.5% | 1%; stop a load ramp |
| Ordinary-read p95 | 400 ms | 500 ms objective breach |
| Student-catalogue p95 | 650 ms | 800 ms objective breach |
| Attempt write p95 | 1.2 s | 1.5 s objective breach |
| Teacher-dashboard p95 | 1.5 s | 2 s objective breach |
| Railway CPU, sustained 10 minutes | 70% | 85% |
| Railway memory | 80% | 90% |
| Database connections | 70% of limit | 85% of limit |
| Database storage | 70% of provisioned | 85% of provisioned |
| Oldest faculty job waiting | 2 minutes | 5 minutes |

#### A1 repeatable report template

Store generated machine reports under gitignored `.tmp/`. Copy only reviewed,
non-sensitive summary values into the table below or a dated issue/PR:

| Evidence | Value to record |
|---|---|
| Date, commit, branch | Exact tested revision |
| Staging shape | Tenant/course/level/subject/chapter/quiz/question/profile/attempt/answer counts |
| API configuration | API replicas, process count, connection-pool settings |
| Worker configuration | Worker replicas, running/queued jobs, oldest queue age |
| Load shape | Selected roles/routes, rounds, concurrency, duration, requests/second |
| Latency | Overall and per-route p50/p95/p99/max |
| Reliability | HTTP status counts, network errors, error rate |
| Database load | Size, connections, top table/index sizes, live/dead tuples, vacuum/analyze state |
| Top queries | Supabase Query Performance observation and reviewed `EXPLAIN (ANALYZE, BUFFERS)` evidence |
| Railway | API and worker peak CPU/memory during the same test window |
| Queue behavior | Oldest wait, completion/failure counts, restart/recovery observation |
| Result | Pass/fail against objectives plus the first observed bottleneck |
| Follow-up | Owner, proposed change, rollback, and retest date |

### A2. Database-side aggregation for heavy dashboards

**Implementation status (25 September 2026):** implemented on branch
`release-a-a2-db-aggregation` and not deployed. The operator reported
migration 68 applied on 25 September 2026; that target project and live function
inventory have not been checked independently. Isolated PostgreSQL
contract/security tests pass; production-shaped staging plans and latency
measurements remain required before A2 operational sign-off.

**Why**

Current teacher endpoints retrieve complete source datasets and aggregate in
Python. The database can count, sum, group, and filter close to the data and
return a compact result.

**How**

1. Define tenant- and actor-scoped PostgreSQL functions for teacher class
   overview, subject metrics, chapter counts, and published-quiz summaries.
2. Apply date ranges where the dashboard does not require all-time detail.
3. Return only the fields needed by the current frontend contracts.
4. Keep authorization in the FastAPI route and repeat tenant/teacher scope
   inside every function query.
5. Restrict function execution to the service role unless a different access
   path is deliberately designed and reviewed.
6. Replace Python-wide aggregation only after contract-comparison tests prove
   the new results match existing behavior.

**Likely files**

- a new numbered migration after migration 67;
- `migrations/schema.sql` where fresh-install consolidation is appropriate;
- `backend/app/api/teacher.py`;
- `backend/app/api/academics.py`;
- possibly `backend/app/api/student.py` for student aggregate paths;
- matching backend regression tests.

**Acceptance criteria**

- Dashboard result totals match the old implementation on the same fixture.
- The API does not download all attempts/questions to calculate summary cards.
- Every tenant-owned query is filtered by the verified tenant.
- Reassigned teachers cannot retain access through an old quiz ID.
- Query plans use expected indexes on the staging dataset.

#### A2 implementation delivered

| Artifact | What changed |
|---|---|
| `migrations/migration-68-teacher-dashboard-aggregates.sql` | Adds service-role-only, `SECURITY INVOKER` aggregate functions for class overview, subject metrics, chapter counts, and published-quiz summaries |
| `backend/app/api/teacher.py` | Replaces the class-overview and published-quiz multi-table downloads with one compact RPC per request |
| `backend/app/api/academics.py` | Replaces chapter counting and subject dashboard aggregation with scoped RPCs |
| `backend/app/lib/supabase_queries.py` | Adds strict JSONB RPC response normalization for direct and PostgREST-wrapped results |
| `scripts/test-teacher-dashboard-aggregates-db.mjs` | Applies migration 68 twice in isolated PostgreSQL and verifies totals, response contracts, tenant isolation, reassignment behavior, privileges, and expected indexes |
| `scripts/teacher-dashboard-explain.sql` | Captures read-only staging `EXPLAIN (ANALYZE, BUFFERS)` evidence for all four functions |
| Backend regression tests | Prove each route sends the verified tenant and actor to exactly one RPC and does not download raw dashboard tables |

Every function checks that the actor is a teacher profile in the supplied
tenant, joins through that teacher's current `teacher_subjects`, and repeats
tenant predicates on operational tables. Quiz ownership by itself is not
enough: after reassignment, former-subject aggregates return no rows. Function
execution is revoked from `public`, `anon`, and `authenticated` and granted
explicitly to `service_role`.

Migration 68 is additive: it creates/replaces four functions and does not
rewrite or delete application rows. Rollout order is migration 68, staging RPC
and query-plan verification, then API deployment. For application rollback,
redeploy the A1 backend; the unused functions may remain safely until a
separately reviewed cleanup migration removes them.

`migrations/schema.sql` is deliberately unchanged. This repository's bootstrap
procedure runs `schema.sql` and then every numbered migration, and existing
analytics functions from migration 36 are likewise retained in their numbered
migration rather than duplicated in the baseline. Migration 68 follows that
established analytics-function convention.

The migration reuses the compound indexes introduced by migration 29 rather
than adding speculative duplicates. Run
`scripts/teacher-dashboard-explain.sql` against the A1 staging dataset and
record scan types, buffers, rows removed, planning time, and execution time.
Repository tests prove the expected indexes exist, but they do not claim which
plans the hosted optimizer will choose at production row counts.

### A3. Cursor pagination and catalogue usability

**Implementation status (26 September 2026):** implemented and pushed on branch
`release-a-a3-cursor-pagination` and not deployed. The operator reported
migration 69 applied on 26 September 2026; the target project and live function
privileges have not been checked independently. Its functions, privileges,
indexes, and consecutive-page contracts pass in isolated PostgreSQL;
production-shaped staging query plans and latency evidence remain required.

**Why**

The database may return thousands of rows successfully while the API response
and browser become slow or unusable. Deep numeric offsets also become more
expensive as page number grows.

**How**

1. Add cursor/keyset pagination using stable pairs such as `(created_at, id)`
   or `(published_at, id)`.
2. Add a bounded page size, normally 20–100 records.
3. Add subject, chapter, status, assignment, and search filters before loading
   details.
4. Return a continuation cursor rather than total datasets.
5. Update frontend pages to use Load More or bounded pages with proper loading,
   empty, and error states.
6. Preserve URL/filter state where the existing dashboard expects refresh
   persistence.

**Initial endpoints**

- student published quiz catalogue;
- faculty published quiz monitor;
- faculty document/history lists;
- student attempt history;
- any question-bank or admin list that can grow without a hard bound.

**Likely files**

- `backend/app/api/student.py`;
- `backend/app/api/teacher.py`;
- `backend/app/api/documents.py`;
- relevant endpoints in `backend/app/api/admin.py` and `practice.py`;
- `frontend/lib/api.ts`;
- corresponding teacher/student/admin dashboard components.

**Acceptance criteria**

- No target list returns the complete dataset by default.
- Page size is enforced server-side.
- Consecutive cursors produce no duplicate or missing rows under a stable
  dataset.
- Direct ID routes still repeat authorization checks.
- A student sees only enrolled and, where applicable, assigned content.

#### A3 implementation delivered

| Artifact | What changed |
|---|---|
| `migrations/migration-69-cursor-pagination.sql` | Adds composite keyset indexes plus service-role-only pages for the student catalogue, student history, and teacher published metrics |
| `backend/app/lib/pagination.py` | Adds strict opaque `(timestamp, UUID)` cursors, page-size enforcement, and PostgREST keyset helpers |
| Student APIs | Published quizzes and combined quiz/practice history now return bounded pages with subject, chapter, assignment, source, and search filters |
| Faculty APIs | Published monitoring, active/archive quiz queues, document selection, and document history return bounded pages; direct detail routes are unchanged |
| Admin API | Institution quiz browsing now uses a created-at cursor with teacher, course, status, and title filters applied before embedded detail loading |
| Frontend query hooks and pages | Replaces fetch-all loops with incremental SWR pages and explicit Load More, loading, empty, error, search, and status controls |
| `scripts/test-cursor-pagination-db.mjs` | Applies migration 69 twice in isolated PostgreSQL and verifies stable continuation, tenant/actor isolation, privileges, contracts, and index creation |

The default page is 25 rows and the hard server maximum is 100. Cursors are
opaque base64url payloads validated as an absolute timestamp plus UUID. List
routes use `(created_at, id)` or `(submitted_at, id)` descending order so equal
timestamps remain deterministic. Student catalogue authorization is repeated
inside PostgreSQL across profile role, tenant, course/level enrollment, active
batch membership, active assignment, and availability windows. Direct-ID
attempt, quiz, performance, archive, and document routes keep their existing
tenant/actor authorization rather than trusting catalogue visibility.

Migration 69 is additive and does not rewrite or delete application rows. The
required rollout order is migration 68, migration 69, isolated/staging RPC
checks, API deployment, then frontend deployment. Rolling the application back
is safe because the new functions and indexes may remain unused; dropping them
is unnecessary during an incident rollback.

### A4. Scalable and fair practice selection

**Implementation status (26 September 2026):** implemented locally on branch
`release-a-a4-fair-practice-selection`. Migration 70 has not been applied
to a hosted project and no API or worker has been deployed. Isolated PostgreSQL
coverage/security checks pass; staging query plans and latency remain required
for operational sign-off.

**Why**

The current selector reads no more than 2,000 eligible rows and shuffles in
Python. With a 100,000-question bank, rows outside the returned pool may rarely
or never be selected.

**How**

1. Add a stable random/sampling key or bucket appropriate for indexed seeking.
2. Select from the verified tenant, enrollment, subject/chapter, approval,
   publication/assignment, type, and difficulty scope.
3. Start from a random key and seek forward; wrap once when necessary.
4. Preserve the maximum exam size and exact requested type counts.
5. Prevent inaccessible batch content from entering practice.
6. Add statistical tests for coverage and deterministic authorization tests.

Do not replace the existing method with `ORDER BY random()` over the whole
bank; that sorts large eligible sets and becomes expensive.

**Likely files**

- a new database migration for any sampling column/index/function;
- `backend/app/services/selector.py`;
- `backend/app/services/batch_access.py`;
- practice and challenge tests.

**Acceptance criteria**

- Questions beyond the first 2,000 rows can be selected.
- Selection latency remains within target on the seeded large bank.
- Type counts and maximum question counts remain correct.
- No pending, rejected, wrong-tenant, unenrolled, draft, archived, or
  unavailable batch question is returned.

#### A4 implementation delivered

| Artifact | What changed |
|---|---|
| `migrations/migration-70-fair-practice-selection.sql` | Adds a stable non-negative sampling key, partial composite seek indexes, a question-link lookup index, and a service-role-only selector RPC |
| `backend/app/services/selector.py` | Replaces the 2,000-row fetch-and-shuffle with bounded random-key RPC seeks and preserves exact per-type selection with a total ceiling of 100 |
| `scripts/test-fair-practice-selection-db.mjs` | Applies migration 70 twice and proves wrap-around, coverage beyond 2,000 rows, type/difficulty filters, tenant/enrollment/review/publication/batch isolation, privileges, and indexes |
| `scripts/fair-practice-selection-explain.sql` | Provides a read-only staging timing and index-inventory check for general and type-specific selection |
| Backend regression tests | Validate RPC scope, batch feature propagation, response-contract rejection, type counts, and the maximum exam size |

Each question receives one stable random `bigint` key. A request chooses a
random starting key, seeks forward through the indexed eligible scope, and
wraps once only when the first seek cannot fill the requested page. The
database returns at most 100 IDs and does not use `ORDER BY random()` or return
the whole eligible bank to Python.

Authorization is repeated inside the function even though the backend uses the
service role: the actor must be a student in the supplied tenant, the question
must belong to the student's enrolled course/level, and the row must be
approved. Standalone approved bank questions remain available. Linked questions
require a published quiz; when batches are enabled, assigned content additionally
requires an active membership and assignment inside their validity windows.

Migration 70 is additive, but its one-time backfill updates every existing
question to assign a sampling key and builds three indexes. Run it first on
production-shaped staging and schedule the hosted migration during a low-write
window. The rollout order is migration 70, isolated/staging contract and plan
checks, API deployment, then practice/challenge smoke tests. Rolling the API
back to A3 leaves the new column, function, and indexes unused and safe.

### A5. Query-plan-driven compound indexes

**Why**

Indexes must match actual combinations of equality, range, join, and ordering
columns. Separate single-column indexes can be less efficient, while excessive
indexes consume storage and slow writes.

**Candidate indexes to validate**

```text
questions
  (tenant_id, review_status, chapter_id, difficulty, type)

quiz_sets
  (tenant_id, subject_id, status, published_at DESC, id)

quiz_sets
  (tenant_id, created_by, status, created_at DESC, id)

attempt_answers
  (tenant_id, question_id, attempt_id)

practice_answers
  (tenant_id, question_id, session_id)

practice_sessions
  (tenant_id, student_id, status, submitted_at DESC)
```

These are investigation candidates, not approved migration SQL.

**How**

1. Capture the slow/high-frequency queries first.
2. Run `EXPLAIN (ANALYZE, BUFFERS)` against production-shaped staging data.
3. Add the smallest useful compound or partial indexes.
4. Re-run plans and load tests.
5. Check insert/update cost and redundant indexes.
6. Run Supabase performance/security advisors before rollout.

**Acceptance criteria**

- Each added index has a recorded query and before/after plan.
- No index is added merely because a column looks important.
- Foreign-key delete/cascade and join paths are covered where necessary.
- Write throughput remains acceptable after index additions.

### A6. Batch and atomic persistence for generated content

**Why**

Individual question and link inserts create many Data API round trips and
require compensating cleanup when a later write fails.

**How**

1. Prefer one atomic database operation for quiz set, variant, questions, and
   link rows.
2. Where an RPC is inappropriate, insert bounded arrays of question/link rows
   rather than one request per row.
3. Keep idempotency keys for retry-safe background work.
4. Preserve the pending-review default and exact answer-shape validation.
5. Preserve job lease checks so a worker that lost ownership cannot commit.

**Likely files**

- a new database function/migration or extension of the reviewed worker commit
  contract;
- `backend/app/services/generation.py`;
- `backend/app/services/blueprint.py`;
- `backend/app/services/quiz_extraction.py`;
- `backend/app/services/faculty_worker.py`;
- generation and worker regression tests.

**Acceptance criteria**

- A failed persistence operation leaves no visible partial quiz.
- Retrying the same durable job does not duplicate content.
- Generated questions remain pending review.
- Insert round trips are materially reduced and measured.

### A7. Realistic load, failure, and isolation verification

**Why**

The existing mocked 15-request test proves handler concurrency only. It does
not establish real capacity.

**Workload scenarios**

1. Student catalogue browsing with filters and pagination.
2. Simultaneous attempt starts.
3. Periodic autosave bursts.
4. Simultaneous submissions and answer persistence.
5. Topic/chapter/exam practice selection.
6. Teacher dashboards on high-volume subjects.
7. Faculty upload/generation queue pressure.
8. Worker restart, lease expiry, retry, and multiple-worker claims.
9. Supabase/Data API transient-read failures.
10. Cross-tenant and cross-role direct-ID attempts.

Run deterministic database/API tests separately from limited provider smoke
tests so AI cost and nondeterminism do not hide database behavior.

**Release A exit criteria**

- The staging data meets the agreed Release A shape.
- Expected 200-user concurrency passes the service objectives.
- The 500-user stress test degrades safely without corrupting attempts.
- No tenant-isolation test fails.
- Attempt and answer counts remain correct after retries.
- Worker restart/recovery tests preserve jobs.
- Capacity results and known limits are recorded before deployment approval.

---

## 6. Release B — structural scale and content lifecycle

**Goal:** reduce long-term attempt duplication, organize very large content
banks, and prepare independent API/worker scaling without changing the core
tenant model.

**Estimated time:** 3–5 additional weeks for two full-time developers after
Release A. The immutable-release migration is the highest-risk item and may
extend the estimate if substantial live attempt data already exists.

### B1. Quiz collections and content lifecycle

**Why**

Chapter alone cannot organize hundreds of quizzes. Students should not browse a
flat list containing every quiz ever generated.

**Proposed concepts**

- collection/series;
- academic session;
- purpose such as topic practice, weekly test, mock, revision, or formal exam;
- display code/title;
- curriculum tags or learning outcomes;
- active availability period;
- generated candidate versus reviewed versus released versus archived state;
- exact duplicate fingerprint;
- current/recommended ordering.

Use existing `batches`, `batch_memberships`, and `quiz_assignments` as the
normal delivery boundary. New collection metadata must not bypass enrollment or
batch access checks.

**Likely changes**

- new tenant-owned collection/series tables or carefully scoped additions to
  `quiz_sets`;
- tenant-qualified foreign keys, RLS, service-role query filters, and indexes;
- faculty collection-management APIs and UI;
- student catalogue filters and current/assigned views;
- migration/backfill for existing quiz sets.

**Acceptance criteria**

- Faculty can locate and manage content without loading the complete bank.
- Students see assigned/relevant content rather than generated history.
- Archived content remains reproducible but is excluded from normal discovery.
- Duplicate detection warns safely without deleting intentional duplicates.

### B2. Immutable quiz releases

**Why**

Current attempt snapshots correctly freeze the paper but copy complete question
content into every attempt. At millions of attempts this creates avoidable
storage growth.

**Target model**

```text
quiz_sets
  └── quiz_releases
        ├── release/version number
        ├── publication metadata
        ├── time/scoring configuration
        └── quiz_release_items
              ├── frozen question content
              ├── frozen options and answer
              ├── marks and order
              └── figure/provenance reference or snapshot

quiz_attempts
  └── quiz_release_id

attempt_answers
  └── quiz_release_item_id
```

One immutable paper is stored per release, while many student attempts refer to
it. An attempt still stores its owner, timing, status, autosave state, and
score; answers remain per student.

**Implementation sequence**

1. Add release tables, tenant-qualified constraints, indexes, and RLS.
2. Create a release atomically when a quiz is published.
3. Start new attempts against a release ID.
4. Grade using release items, not mutable authoring rows.
5. Keep the legacy snapshot read path for old attempts.
6. Backfill only when safe and verifiable; do not discard existing snapshots
   merely to save space.
7. Compare old/new grading results on identical fixtures.
8. Remove legacy behavior only in a later separately approved migration.

**Likely files**

- new migration and `migrations/schema.sql` consolidation;
- publication functions introduced by migrations 51 and 67;
- `backend/app/api/quiz.py`;
- `backend/app/api/student.py`;
- `backend/app/api/practice.py` if practice releases share the model;
- grading/scoring access helpers;
- teacher reports and attempt-download paths;
- frontend API contracts only where response identifiers change.

**Acceptance criteria**

- A published release is immutable.
- A later faculty edit/copy cannot change an existing attempt.
- Taking responses never expose answer keys.
- Graded responses reproduce the exact released paper.
- Concurrent starts reference one release rather than duplicating its complete
  questions.
- Existing legacy attempts remain readable and gradeable.
- Account deletion and content-retention rules remain correct.

### B3. Retention and cold-data policy

**Why**

Temporary processing data and operational logs should not grow forever, while
academic and audit records may require long retention.

**Classify before deleting anything**

| Data | Default direction |
|---|---|
| Published releases and graded attempts | Retain according to academic/legal policy |
| Attempt answers and reports | Retain according to academic/legal policy |
| In-progress autosave state | Clear after finalization and bounded recovery window |
| Document chunks | Eligible for archival/removal after verified processing if regeneration policy permits |
| Completed worker checkpoints | Eligible for compacting after a recovery window |
| API provider-call metadata | Retain for bounded cost/health analysis |
| Events | Keep indexed recent history; roll up/archive only when volume requires it |
| Source documents and figures | Follow institution content-retention policy |

The old retention cron was deliberately removed after migration 59 eliminated
raw AI payload columns. Do not recreate it without a new approved policy and
schema-specific implementation.

**Acceptance criteria**

- Retention rules are documented by data category.
- Academic reproducibility and account-deletion obligations are preserved.
- A dry-run/report mode identifies affected rows and objects before deletion.
- Material deletion requires separate authorization and verification.

### B4. Independent API and worker scaling

**Why**

Student request traffic and AI generation workloads have different resource
profiles. They must scale independently.

**How**

- Keep API replicas stateless.
- Add Railway API replicas only after load testing identifies an API-process
  bottleneck.
- Add worker replicas to use the existing `FOR UPDATE SKIP LOCKED` queue safely.
- Preserve global and per-tenant job caps until provider cost, quotas, and
  database write capacity justify changing them.
- Monitor the Supabase/Data API and database pressure because every API/worker
  replica adds upstream concurrency.
- Use backpressure and visible queue state rather than unlimited generation.
- Deploy API and worker from the same verified revision whenever shared job
  contracts change.

**Acceptance criteria**

- Two or more workers never commit the same job.
- A noisy institution cannot consume all worker capacity.
- API scaling does not exhaust upstream connections or degrade submissions.
- Health checks distinguish API liveness from worker readiness.

### B5. Conditional rollups and partitioning

These are **not automatic Release B requirements**. Implement only when
measurements justify them.

Potential future steps:

- daily tenant/metric rollups for expensive long-range analytics;
- time-based partitions for `events`, answer tables, or API logs;
- cold archival of old operational data;
- larger Supabase compute or read replicas.

Partitioning normally becomes useful at tens/hundreds of millions of rows or
when vacuum, retention, and time-range queries become operationally difficult.
Do not partition by tenant merely because ten tenants exist.

---

## 7. Timeline and ownership

### 7.1 Two-developer schedule

| Week | Primary work | Suggested ownership |
|---|---|---|
| 1 | Staging data, baseline measurements, monitoring | Both; one owns test tooling, one owns operational metrics |
| 2 | Database aggregates and query-plan analysis | Backend/database owner, with contract tests by teammate |
| 3 | Cursor APIs and frontend pagination/filtering | Split backend API and frontend integration |
| 4 | Practice sampling and validated indexes | Backend/database owner plus security tests |
| 5 | Batch/atomic writes and realistic load tests | Both |
| 6 | Fixes, tenant-isolation regression, release evidence | Both |
| 7 | Collections/content lifecycle | Split schema/API and frontend |
| 8–9 | Immutable releases and dual-read compatibility | Both; mandatory joint review |
| 10 | Retention policy, scale tests, Release B stabilization | Both |
| 11 | Contingency for migration/performance issues | If required |

### 7.2 Estimate summary

- Release A: **4–6 weeks** for two full-time developers.
- Release B: **3–5 additional weeks**.
- Complete program: **7–11 weeks** for two full-time developers.
- One full-time developer: approximately **10–15 weeks**.
- Part-time team: likely **3–5 calendar months**.

These estimates are not contractual. The largest uncertainty is migrating
attempts from duplicated snapshots to immutable releases while preserving old
results.

---

## 8. Multi-tenant and security requirements

Every Release A/B change must preserve these rules:

1. The authenticated profile is the authority for `tenant_id` and `role`.
2. Browser-provided tenant, role, owner, score, or answer-key data is never
   trusted.
3. The backend service-role client bypasses RLS, so every tenant-owned query and
   write must explicitly filter/set the verified tenant.
4. New tenant tables require tenant ownership, foreign keys that cannot cross
   tenant boundaries, RLS, and appropriate privileges.
5. Students can access only their enrolled Course + Level subjects and valid
   batch assignments.
6. Teachers can access only explicitly assigned subjects and their authorized
   content/results.
7. AI-generated questions remain hidden until teacher approval.
8. Correct answers stay hidden until the applicable attempt is graded.
9. Immutable releases must not expose answer keys through browser-accessible
   Supabase tables.
10. Direct-ID access is reauthorized; knowing a UUID never grants access.
11. No service-role key, JWT, personal data, raw prompt, or answer key is logged
    or sent to the public frontend outside its authorized response.

---

## 9. Database migration and rollout rules

1. Use the next numbered migration after the repository's current latest
   migration; do not edit an already-applied migration to change history.
2. Keep migrations additive and backward-compatible wherever possible.
3. Preserve existing attempts and academic content unless deletion is
   explicitly approved.
4. Update `migrations/schema.sql` when the project convention requires the
   fresh-install baseline to include the final effect.
5. A migration file in Git does not prove it ran in production.
6. Validate SQL on a safe staging database with production-shaped data.
7. Run security and performance advisors plus relevant query plans.
8. Deploy compatible API code only after required migrations are confirmed.
9. Worker-sensitive code requires a separately authorized worker deployment.
10. Use feature flags or dual-read/dual-write compatibility for the immutable
    release transition.
11. Every rollout needs a rollback/disable path that does not corrupt attempts.

---

## 10. Verification matrix

| Concern | Required evidence |
|---|---|
| Correct totals | Old/new aggregate contract tests on the same fixtures |
| Query performance | Before/after `EXPLAIN (ANALYZE, BUFFERS)` on staging data |
| Pagination | Cursor continuity, stable ordering, no duplicate/missing rows |
| Tenant isolation | Cross-tenant API and direct-ID regression tests |
| Teacher scope | Reassignment revokes previous subject/result access |
| Student scope | Enrollment and batch-assignment tests |
| Answer secrecy | Taking payloads omit keys; graded reports include authorized results only |
| Attempt integrity | Concurrent start limits and retry-safe submission tests |
| Worker durability | Restart, lease expiry, retry, and multi-worker claim tests |
| Storage behavior | Table/index/bucket growth recorded during load test |
| API capacity | 200 expected and 500 stress concurrent-user scenarios |
| Failure behavior | Timeouts/transient read failures degrade safely |
| Deployment | API and worker health plus a small real queued-job smoke test |

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| New aggregate RPC returns different numbers | Run old/new implementations against identical fixtures before switching |
| Added index slows writes or consumes excessive storage | Require query-plan evidence and check redundant indexes |
| Cursor ordering changes while rows are inserted | Use stable composite cursor including unique `id` |
| Sampling leaks unavailable questions | Reuse enrollment, review, publication, and batch gates in the database selection contract |
| Release migration changes grading | Dual-read legacy snapshots and compare deterministic results |
| Multiple workers duplicate a job | Keep lease token, expiry, atomic claim, and idempotent commit checks |
| API replicas overwhelm Supabase | Scale only after measuring upstream connections/query pressure |
| Faculty generates unusable volume | Collections, review queue, archive lifecycle, quotas, and assigned delivery |
| Human review becomes the bottleneck | Track review backlog; improve organization and review UX without auto-approving AI content |
| Production schema differs from Git | Perform authorized live migration/inventory checks before rollout |

---

## 12. Deliberately deferred architecture

The first 10 institutions do not by themselves justify:

- one database per institution;
- tenant sharding;
- microservices for each feature;
- Kafka or another streaming platform;
- a dedicated analytics warehouse;
- read replicas before query optimization;
- table partitioning before table/maintenance metrics require it;
- populating millions of vector embeddings before semantic search has an
  approved use case and cost model.

These remain future options, not Release A promises.

---

## 13. Decisions that can be postponed until pilot evidence

The founders do not need to know exact customer behavior today. The following
decisions can use data from the first one to three months:

- whether expected concurrency should increase beyond 200;
- whether 500 concurrent students must become a normal rather than stress
  target;
- whether immutable releases must cover practice sessions as well as published
  teacher quizzes;
- how long documents, figures, chunks, events, logs, and attempts must be kept;
- when database compute should be upgraded;
- whether daily metric rollups are necessary;
- whether answer/event tables are large enough to partition;
- whether a particular institution needs physical isolation for contractual or
  legal reasons.

---

## 14. Release sign-off checklists

### Release A

- [x] Repeatable tenant-safe synthetic content seed is implemented and locally verified.
- [x] Read-only route baseline and database-health report tooling are implemented.
- [ ] The production-shaped dataset has been executed on isolated staging.
- [ ] The staging capacity baseline and provider metrics are recorded.
- [x] Teacher aggregate functions, API integration, and isolated contract/security tests are implemented.
- [x] The operator reported migration 68 applied on 25 September 2026.
- [ ] Migration 68 and its function privileges are independently verified on the target project before deploying the A2 API.
- [ ] Staging query plans and before/after latency are recorded on the A1 dataset.
- [x] Target large lists use bounded cursor pagination in repository code.
- [x] Student catalogue has meaningful filters and does not load everything.
- [x] The operator reported migration 69 applied on 26 September 2026.
- [ ] Migration 69 and its function privileges are independently verified on the target project.
- [x] Large-bank practice sampling is fair and indexed in repository code and isolated PostgreSQL checks.
- [ ] Migration 70 is applied and independently verified on the target project.
- [ ] Added indexes have before/after plan evidence.
- [ ] Generated quiz persistence is atomic or safely batched/idempotent.
- [ ] 200 expected-concurrency scenario passes.
- [ ] 500 stress-concurrency scenario fails safely or passes.
- [ ] Tenant/role/direct-ID security suites pass.
- [ ] Worker restart and recovery tests pass.
- [ ] API and worker deployment requirements are documented.
- [ ] Remaining capacity limits are recorded honestly.

### Release B

- [ ] Quiz collection/content lifecycle is approved and implemented.
- [ ] Generated, reviewed, released, assigned, and archived states are clear.
- [ ] Immutable release schema and tenant constraints are reviewed.
- [ ] New attempts reference immutable releases.
- [ ] Legacy attempts remain readable.
- [ ] Grading equivalence tests pass.
- [ ] Answer-key secrecy tests pass.
- [ ] Retention policy is approved by data category.
- [ ] Multiple worker/API replica tests pass if replicas are enabled.
- [ ] Rollups/partitioning were either justified by measurements or explicitly
      deferred.
- [ ] Staging migration and rollback drill passes.
- [ ] Authorized production rollout evidence is recorded separately.

---

## 15. Repository evidence reviewed

The plan is grounded in the following current repository areas:

- `migrations/schema.sql` and numbered migrations through migration 70;
- `migrations/migration-29-staff-dashboard-performance.sql`;
- `migrations/migration-36-super-admin-aggregates.sql`;
- `migrations/migration-43-faculty-background-jobs.sql`;
- `backend/app/api/student.py`;
- `backend/app/api/teacher.py`;
- `backend/app/api/academics.py`;
- `backend/app/api/documents.py`;
- `backend/app/api/quiz.py`;
- `backend/app/services/selector.py`;
- `backend/app/services/generation.py`;
- `backend/app/services/blueprint.py`;
- `backend/app/services/faculty_worker.py`;
- `backend/app/lib/supabase.py`;
- `backend/Dockerfile` and `backend/Dockerfile.worker`;
- `backend/tests/test_quiz_generation_load.py`;
- `docs/deploy-runbook.md`;
- `docs/architecture-scalability-plan.md` as an older draft whose claims were
  rechecked rather than copied as current truth.

This review was repository-only. It did not run SQL against the live Supabase
project, inspect live table sizes/query plans, change Railway resources, or run
a production load test.

---

## 16. Final implementation commitment

For planning purposes, use this statement:

> The first production capacity target is 10 institutions, 10,000 registered
> students, 200 expected concurrent students, 500 stress-test concurrent
> students, one million attempts per year, and 10–20 million answer rows per
> year. Release A will establish bounded queries and prove that envelope.
> Release B will organize high-volume content and reduce long-term attempt
> duplication through immutable quiz releases. Larger infrastructure or data
> architecture changes require measured evidence.

When implementation begins, convert each Release A/B work package into a
separate issue or pull request with its own migration, tests, rollout evidence,
and rollback notes. Do not treat this README as authorization to migrate,
deploy, delete data, or change paid provider resources.
