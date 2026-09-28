# Release A5 query-plan evidence

**Captured:** 26 September 2026

**Environment:** isolated embedded PostgreSQL (PGlite), no network, credentials,
personal data, or hosted database access.

**Dataset:** 20,002 answer rows per table: 20,001 for the target tenant plus one
cross-tenant row sharing the target question. The tenant-scoped result remained
exactly one row before and after migration 71.

This file records deterministic local evidence for the two indexes approved in
A5. It does not replace the required production-shaped staging capture or write
load test.

## Query 1 — quiz answer authorization

```sql
select attempt_id
from public.attempt_answers
where question_id = :question_id
  and tenant_id = :tenant_id;
```

| Measurement | Before migration 71 | After migration 71 |
|---|---:|---:|
| Scan | `Index Scan` on `idx_answers_tenant` | `Bitmap Index Scan` on `idx_attempt_answers_question_tenant_attempt` plus one exact heap block |
| Rows removed by filter | 20,000 | 0 |
| Data buffers | 245 hits | 1 hit + 2 reads |
| Execution time | 2.425 ms | 0.020 ms |

## Query 2 — practice answer authorization

```sql
select session_id
from public.practice_answers
where question_id = :question_id
  and tenant_id = :tenant_id;
```

| Measurement | Before migration 71 | After migration 71 |
|---|---:|---:|
| Scan | `Index Scan` on the `(session_id, question_id)` unique index | `Bitmap Index Scan` on `idx_practice_answers_question_tenant_session` plus one exact heap block |
| Rows removed by filter | 1 | 0 |
| Data buffers | 151 hits | 1 hit + 2 reads |
| Execution time | 0.607 ms | 0.014 ms |

The exact timings are illustrative and machine-dependent. The durable evidence
is the change to a tenant-qualified question-first index path and the
elimination of the broad scan/filter work.

## Redundancy and write-cost result

Migration 71 removes `idx_answers_attempt` and
`idx_practice_answers_session`. Their leading columns were already covered by
the unique `(attempt_id, question_id)` and `(session_id, question_id)` indexes.
The unique indexes remain present, and each answer table exchanges one
redundant index for one useful index. Its index count therefore does not grow.

## Remaining hosted evidence

Before A5 rollout approval:

1. Run `scripts/query-plan-indexes-explain.sql` before and after migration 71
   against the same fake question in the A1 production-shaped staging dataset.
2. Save both hosted plans and compare scan type, filtered rows, buffers,
   planning time, and execution time.
3. Run the A1 write/load scenario and confirm acceptable answer submission
   throughput and error rate.
4. Review Supabase performance and security advisors.
