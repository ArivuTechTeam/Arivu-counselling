# Release A7 capacity, failure, and isolation verification

**Repository status:** tooling implemented locally on
`release-a-a7-load-verification`. No hosted load run has been performed.

**Purpose:** produce repeatable evidence for the expected 200-user launch load
and a 500-user stress load without using production data or hiding corrupted
attempts behind successful HTTP counts.

## Safety boundary

- Use an isolated staging Supabase project and staging API/worker services.
- Apply migrations through 72 and deploy the matching API and worker revision.
- Set `CAPACITY_PRODUCTION_HOST` to the real production API hostname. Both load
  tools refuse that host.
- Use only disposable synthetic students. Never use customer accounts.
- Keep bearer tokens in `.tmp/a7-student-tokens.json`, mode `0600`. The file is
  ignored by Git and must be deleted after the run.
- Do not run paid AI generation at 200/500 concurrency. Queue pressure and
  recovery use a small bounded synthetic job drill after the HTTP load.

The A1 reader remains GET/HEAD-only. A7 uses a separate runner because its
student workflow deliberately creates attempts, practice sessions, and answer
rows.

## Staging data and disposable actors

1. Seed the approved 10-institution shape incrementally with
   `scripts/capacity-seed.sql`: smoke, 1%, 10%, then the agreed launch shape.
2. Create at least 500 disposable students through supported Supabase Auth
   administration, distributed across all 10 tenants, and enroll them normally.
3. Ensure each student can reach one published quiz variant and one subject
   containing at least ten approved practice questions.
4. Put the short-lived access tokens and non-secret scope IDs in this untracked
   file:

```json
{
  "version": 1,
  "actors": [
    {
      "token": "DISPOSABLE_STAGING_ACCESS_TOKEN",
      "variant_id": "ACCESSIBLE_VARIANT_UUID",
      "subject_id": "ENROLLED_SUBJECT_UUID",
      "practice_mode": "smart",
      "chapter_id": null
    }
  ]
}
```

Use a unique token/student for every virtual user. `practice_mode` can be
`smart`, `chapter`, or `revision`; chapter mode requires `chapter_id`. The
runner rejects duplicate tokens and credential files readable by other users.

## Execute the expected and stress profiles

Record the UTC start time immediately before each run.

Read traffic uses the A1 route mix, including catalogue, student stats,
teacher aggregates, published monitoring, admin overview, and worker health:

```bash
cd backend
venv/bin/python scripts/capacity_baseline.py \
  --base-url https://STAGING_API_HOST \
  --allow-remote-staging --confirm-host STAGING_API_HOST \
  --role public --role student --role teacher \
  --role institution_admin --role super_admin \
  --rounds 100 --concurrency 200 \
  --output ../.tmp/a7-read-expected.json

venv/bin/python scripts/capacity_baseline.py \
  --base-url https://STAGING_API_HOST \
  --allow-remote-staging --confirm-host STAGING_API_HOST \
  --role public --role student --role teacher \
  --role institution_admin --role super_admin \
  --rounds 200 --concurrency 500 \
  --output ../.tmp/a7-read-stress.json
```

Write traffic runs ten correlated operations per disposable student: catalogue,
quiz start/autosave/submit/graded receipt, and practice preview/start/autosave/
submit/graded receipt. IDs and response bodies remain in memory and are not
written to the metrics report.

```bash
chmod 600 .tmp/a7-student-tokens.json
cd backend
CAPACITY_PRODUCTION_HOST=api.example.com \
venv/bin/python -m scripts.release_a_workflow_load \
  --base-url https://STAGING_API_HOST --confirm-host STAGING_API_HOST \
  --confirm-write A7_WRITE_TEST --profile expected \
  --token-file ../.tmp/a7-student-tokens.json \
  --output ../.tmp/a7-write-expected.json

CAPACITY_PRODUCTION_HOST=api.example.com \
venv/bin/python -m scripts.release_a_workflow_load \
  --base-url https://STAGING_API_HOST --confirm-host STAGING_API_HOST \
  --confirm-write A7_WRITE_TEST --profile stress \
  --token-file ../.tmp/a7-student-tokens.json \
  --output ../.tmp/a7-write-stress.json
```

The expected profile requires 200 tokens; stress requires 500. A workflow is
counted intact only if both graded receipts contain exactly the questions
returned at start.

## Database and worker evidence

After each profile, run the following in the staging SQL editor and export all
result grids:

```sql
set arivupro.capacity_started_at = 'UTC_RUN_START';
-- Then execute scripts/a7-integrity-report.sql
-- Also execute scripts/capacity-database-report.sql
```

Every violation reported by `a7-integrity-report.sql` must be zero. This covers
graded answer-count mismatches, answer rows on open sessions, duplicate answers,
cross-tenant answer links, and expired worker leases.

For the worker recovery drill, enqueue only a small synthetic job set, then:

1. Confirm jobs are claimed across available workers without duplication.
2. Stop one worker after a checkpoint.
3. Wait for lease expiry and restart or replace it.
4. Confirm another worker resumes, the old lease cannot commit, and replaying a
   successful finish returns the original quiz IDs.
5. Save worker queue age, retry count, API/worker CPU and memory, and database
   connections before, during, and after the drill.

`scripts/test-faculty-jobs-db.mjs` is the deterministic local contract for
claiming, leases, cancellation, rollback, retry exhaustion, and replay. The
staging drill proves the deployed API/worker/database combination.

## Failure and isolation matrix

Run deterministic suites before staging:

```bash
node scripts/test-cursor-pagination-db.mjs
node scripts/test-fair-practice-selection-db.mjs
node scripts/test-faculty-jobs-db.mjs
node scripts/test-atomic-quiz-persistence-db.mjs
cd backend
venv/bin/python -m pytest -q \
  tests/test_release_a_workflow_load.py \
  tests/test_student_experience.py \
  tests/test_security_regressions.py \
  tests/test_supabase_client_singletons.py \
  tests/test_faculty_jobs.py \
  tests/test_worker_health.py
```

Before approval, also make direct-ID requests with a second-tenant student and
with the wrong role. Quiz attempts, practice sessions, documents, faculty jobs,
and teacher aggregates must return the documented 403/404 response and must not
change row counts. Temporarily inject a staging Data API 502/503 or use the
repository client failure tests; reads may retry, but writes must not duplicate
attempts or answers.

## Provisional pass criteria

| Evidence | Expected profile | Stress profile |
|---|---|---|
| Concurrency | 200 | 500 |
| Read-route error rate | below 1% | record actual; no uncontrolled retry storm |
| Read p95 | each route meets `capacity_scenario.json` | record degradation and bottleneck |
| Student workflow | 200/200 intact | pass, or degrade with no integrity violations |
| Integrity SQL | every violation is zero | every violation is zero |
| Tenant/direct-ID checks | zero failures | zero failures |
| Worker recovery | no duplicate quiz; queue recovers | no duplicate quiz; bounded queue recovery |

The stress profile is not required to stay under expected-profile latency, but
it must never corrupt attempts, duplicate answers, cross tenant boundaries, or
leave unrecoverable jobs. Any nonzero integrity violation blocks Release A.

## Evidence record

Store reports outside Git if they contain hostnames or operational details.
The release decision should record:

- Git commit, migration inventory, API revision, and worker revision;
- seed label and exact row counts;
- four JSON load reports and both SQL exports;
- Supabase CPU/I/O/connections and top-query evidence;
- Railway API/worker CPU, memory, restarts, and queue-age evidence;
- all failure/isolation outcomes;
- measured safe concurrency, bottleneck, and scaling action;
- reviewer, date, and explicit approve/reject decision.

Local tests and tooling are not proof of hosted capacity. Release A remains
unsigned until these staging artifacts exist.
