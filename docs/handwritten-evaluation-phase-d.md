# Handwritten evaluation Phase D: learning data

Phase D derives a mistake library, revision queue, and subject analytics only
after Phase C has committed a fully evaluated submission. It never changes the
evaluation, question marks, or submission score. Each follow-on step is
best-effort, so a learning-data failure cannot roll back a committed evaluation.

Mistakes are rebuilt deterministically from persisted question results. Ignored
choices, review-required answers, and full-mark answers create no mistakes. A
blank counted answer creates one `not_attempted` mistake. Other score gaps are
allocated proportionally across deficient fixed criteria, with the last
criterion absorbing the one-decimal rounding residual.

Chapter resolution is deliberately limited to reliable data:

1. the frozen rubric topic;
2. the longest matching chapter name belonging to the evaluation paper's tenant
   and subject;
3. `Other topics`.

There is no DB-question/chapter lookup because Phase C question results do not
reliably carry a verified `questions.id`.

## Deliberate ExamApp analytics compatibility

Quiz Generator follows ExamApp's actual live behavior, not the unused shape of
its `StudentAnalytics` model. Consequently,
`handwritten_student_analytics` intentionally has no `weak_chapters`,
`top_mistake_categories`, `presentation_scores`, or `streak_count` columns.
ExamApp's updater never populates those fields; its dashboards compute weak
areas from current mistake and revision queries.

The `/api/v1/handwritten-learning/weak-areas` endpoint does the same here:
chapter data comes live from unresolved `handwritten_revision_items`, and
mistake-category patterns are aggregated live from `handwritten_mistakes` for
the student's latest evaluated submission per paper. This is intentional and
prevents stale duplicate analytics state.

`score_history` is Quiz Generator's own stable contract. Every array item is
exactly `{evaluation_id, percentage, date}`; it is not intended to be consumed
as an ExamApp `StudentAnalytics` payload.

Apply `migration-82-handwritten-learning.sql` before deploying this worker and
API version. The three new tables and their reconciliation functions are
service-role-only; API authorization uses the server-side profile tenant and
role on every read.
