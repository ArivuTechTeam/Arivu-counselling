# Phase 5: safe quiz duplication and release

Implemented increment: independent copies, preserved provenance, stale-edit
checks and atomic publication. The searchable question library and templates
remain subsequent increments. Phase 4 is not rebuilt; the current figure
implementation remains in use.

## Enable and test

1. Deploy the matching API, frontend and worker code in staging first. The new
   `QUIZ_REUSE_ENABLED` setting defaults to false.
2. Confirm the current merged schema, including the existing figure-link
   migration 50. Back up the database. During a short maintenance window, run
   `migrations/migration-51-safe-quiz-reuse.sql` in Supabase SQL Editor. It is
   additive and rerunnable. It does not delete quiz/attempt/image records.
3. Set `QUIZ_REUSE_ENABLED=true` in the backend environment and restart the API
   and workers. Docker also passes this variable from the root environment.
   Restart/rebuild the frontend as appropriate for your deployment.
4. Open an existing quiz's review page and choose **Duplicate as draft**.
   The copied quiz opens in review with separate questions and retained answers,
   review evidence, order, marks overrides, time limits and figure references.
5. Edit the copy and confirm the original is unchanged. Approve edited items,
   then publish. Refresh the original and check an existing student's result.
6. Try editing from a second stale tab; it must require a reload. Try publishing
   while another tab changes the draft; it must reject the stale publication.
7. Check paper/answer PDF order and marks, and the existing figure behavior.
   This increment does not add missing visual support to other delivery paths.

No hosted migration was applied automatically. Code with the feature disabled
keeps the previous publish path. The migration deliberately does not
retroactively freeze existing quizzes; the atomic feature path records and
protects releases once enabled. Disabling the switch does not remove release
protection already recorded by the enabled path. Retain the schema and matching
code; do not drop protection columns or unfreeze papers to work around errors.

## Behavior and boundaries

- The migration is behavior-neutral while the feature flag is off. Future
  releases through the enabled atomic path retain `released_at` through
  archive/restore and freeze their released structure. Existing historical
  quizzes are not silently reclassified during migration rollout.
- Released questions, links, ordering, marks and variant settings are protected.
  Archive/restore changes availability; it does not make a released paper editable.
  Duplicate it for edits. Existing student snapshots and scores are untouched.
- Deleting frozen questions or altering their retained figure link is rejected.
  Author/reviewer anonymization remains allowed. Source-asset deletion/retention
  needs the Phase 6 drill; do not delete referenced assets to bypass protection.
- Copies receive new IDs and origin/source-quiz lineage. Copied figures reuse
  their existing IDs; no new figure extraction, AI request or public asset URL is
  created. Original approval metadata is preserved on unchanged copies; editing
  content follows the existing reapproval rules. Copied drafts are not published
  automatically and do not inherit attempts or scores.
- Copy creation and its request record are transactional. A request key is
  retained through a failed response and browser refresh; retry returns the same
  draft. Changing source/title under that key is rejected. The initial limit is
  500 linked questions per copied quiz.
- Publication locks the quiz and its question rows, compares the loaded revision,
  validates review state/marks and commits totals, protection and publication
  together. Database errors roll back all changes. Content changes after loading
  require a reload; no silent fallback to the non-atomic path occurs when enabled.
- API answer-shape validation remains in place. SQL functions are service-only,
  recheck institution, teacher ownership and subject access. Copy/publication
  events commit with their operation; copies are not recorded as AI generations.
- Question editing sends an expected content version. Regeneration also rejects
  a write if the question changed while the model ran. Existing figure operations
  retain their implementation and are blocked only for protected releases.
- Review/PDF question marks now honor existing per-quiz marks overrides.

## Verification

Final local results: 526 backend tests and 117 subtests passed; frontend production
build, lint/types, queue integration tests, quiz-reuse integration tests and the
existing frontend timeout regression script passed. Hosted migration and
interactive staging acceptance have not been performed.

`node scripts/test-quiz-reuse-db.mjs` runs migration reruns, copy replay/conflict,
independent edits, figure and provenance preservation, historical snapshot/score
preservation, stale publication, immutability, archive/restore, access revocation,
browser-role denial, event replay and transactional failure tests in isolated
Postgres (PGlite). It is included in PR CI.

Backend regressions exercise feature-off compatibility, teacher authorization,
expected versions, safe errors and rejecting a detail response whose publication
token changed during loading. The frontend production build checks types/lint.

PGlite runs one database connection: true multi-connection concurrency, hosted
PostgREST behavior and interactive staging/browser acceptance remain rollout
checks. No live AI generation or hosted writes were used to claim completion.
