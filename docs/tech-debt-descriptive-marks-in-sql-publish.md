# Tech debt: descriptive marks still counted in SQL-computed quiz totals

Written 2026-09-30. Status: **open, not scheduled.** Found while fixing descriptive
questions in the ordinary quiz flow (branch `fix/descriptive-questions-and-extraction-marks`).

## What was fixed, and what was not

Descriptive questions (extracted in paper mode) cannot be scored in a normal quiz.
The Python side now leaves them out:

- `backend/app/api/student.py` filters them when an attempt starts and when an old
  `question_snapshot` is read, so `max_score` and results exclude them.
- `backend/app/api/quiz.py` (`publish_quiz_set`, the non-reuse path) leaves their marks
  out of `quiz_variants.total_marks`.

The **SQL publish functions still sum every approved question**, including descriptive
ones. A code-only change cannot reach them.

## Where the SQL counts them

All of these compute `total_marks` as `sum(coalesce(l.marks_override, q.marks))` over
approved questions, with no `q.type` filter:

| Function | Migration | Line | When it runs |
|---|---|---|---|
| `publish_quiz_atomic` | `migration-51-safe-quiz-reuse.sql` | 144 | Publishing when quiz reuse is enabled. Also called by `publish_quiz_to_batches_atomic` (migration 67, line 31) |
| `publish_quiz_blueprint_atomic` | `migration-75-atomic-review-and-regeneration.sql` | 229 | Blueprint publishing |
| `persist_generated_quiz` | `migration-72-atomic-quiz-persistence.sql` | 137 | Extraction and generation, at draft creation. Publish overwrites it (except when `released_at` is set) |

`publish_quiz_with_rejected_purge_atomic` (`migration-75`, line 132) delegates to
`publish_quiz_atomic`, so it is fixed by the same change. The batch variant with purge
(`publish_quiz_to_batches_with_rejected_purge_atomic`, line 154) was not read.
`schema.sql` holds copies of these definitions (for example line 1805), so it needs the
same change.

## Who is affected

Only code that reads the **stored** `quiz_variants.total_marks`:

- `backend/app/api/teacher.py` (lines ~120, ~360, ~521): teacher quiz performance and
  student rollups.
- `backend/app/api/practice.py` (~1253): leaderboard maximum.

The student-facing attempt, result and score are already correct, because they use the
live snapshot. A quiz published through these paths with descriptive questions shows an
understated percentage in those teacher and leaderboard views.

## What a fix needs

1. A new migration that recreates `publish_quiz_atomic` and `publish_quiz_blueprint_atomic`
   (and `persist_generated_quiz`, for consistency) with `and q.type <> 'descriptive'` in the
   total's `select`. The `quiz_empty` check should keep counting descriptive questions, so a
   paper-only set still publishes. The Python path already behaves that way.
2. The same edit in `schema.sql`.
3. A decision on existing rows: stored totals for already-published variants are not
   corrected by the migration. One live variant was checked on 2026-09-30 and was already
   consistent (stored 6, recomputed 6), but other tenants or environments were not checked.
4. Tests: `scripts/test-quiz-reuse-db.mjs` covers the SQL publish path.

## Why it was left

Out of scope for the change that found it. It needs a migration against the hosted
Supabase project, which should be a separate, explicitly approved task.
