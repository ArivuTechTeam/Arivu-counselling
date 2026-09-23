# Phase 5 foundation checks

22 September 2026, branch `changes-pavyaa`. This is the first reliability
increment of the approved Phase 5/6 plan, not completion of the full roadmap.
No new migration is required. The existing alternative figure implementation
has not been changed.

## Implemented

- The fallback final-generation lookup now includes the source document, in
  addition to tenant, teacher and request settings. Two documents with identical
  quiz settings no longer reconnect to the same in-progress job. This does not
  make the legacy select-then-insert path safe against simultaneous submissions;
  the dedicated faculty queue already provides transactional intent uniqueness.
- Final-generation failures save a stable public message instead of arbitrary
  exception text. This protects future failures; old error rows are not rewritten.
- Added `python -m app.services.deployment_check`, a read-only schema preflight.
  Run from `backend` using the project's virtual environment and the same
  environment as the API/worker. Output contains status and local filenames,
  not document contents, keys, database row values or exception payloads.
- CI now runs the existing isolated Postgres queue integration test. It exercises
  migration reruns, idempotency, quota replay, leases, atomic rollback,
  cancellation, checkpoint recovery, tenant caps and authorization.

## Verified configuration and limits

Read-only checks against the configured database passed for questions, attempt
snapshots, analysis jobs, API logs, faculty jobs and existing figure/link fields.
The current environment enables the dedicated faculty queue. These checks do
not prove hosted function bodies or migration history match repository SQL.
They do not prove worker liveness, storage permissions or live AI completion.

The actual Generate screen calls `queueBlueprintQuizGeneration` /
`queueGenerationFromJob`. When enabled, these submit to `faculty_jobs`. Otherwise
they use the async final-generation routes backed by in-process threads.
Topic analysis also retains its existing thread-based runner. Queued rows alone
do not guarantee processing survives an API restart; do not advertise that
guarantee for the fallback. The earlier synchronous API helpers still exist for
compatibility.

Current repository numbering is 41 (review default), 42 (API logs), 43 (faculty
jobs), followed by the user's 45/46 figure migrations. Older branch documents
describe different filenames. Do not replay historical SQL based on numbers
alone; inspect applied objects/history before the next schema change.

## Validation

- Starting working-tree baseline: 512 backend tests and 117 subtests passed.
- After the changes: 516 backend tests and 117 subtests passed. The existing
  frontend timeout regression script and Git whitespace checks also passed.
- Four new tests cover document-scoped job reconnection, safe error storage,
  read-only preflight behavior and missing-schema failure without payload leaks.
- Isolated Postgres queue integration tests passed locally. CI execution on
  GitHub remains pending until these changes are pushed and a PR runs.
- No paid AI request, hosted migration or database mutation was performed.

## Next gates

1. Check actual worker/service readiness and run a small permissioned end-to-end
   generation/import test with request/job correlation. The original live timeout
   report remains unverified; these changes are not a claim that it is fixed.
2. Reconcile hosted function definitions and migration history before creating
   the safe-copy/publication migration. Use a staging upgrade fixture; do not
   drop or recreate working figure tables.
3. Implement atomic publication and independent question copies with lineage,
   provenance, revision checks and historical-attempt compatibility. Then expose
   the question library and quiz duplication UI.
