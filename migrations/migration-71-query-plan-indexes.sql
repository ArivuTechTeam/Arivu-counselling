-- Migration 71 — query-plan-driven index validation for Release A5.
-- Apply after migration 70 and before the A5 API is considered release-ready.
--
-- The two new indexes match the student question-access lookups in
-- backend/app/services/student_access.py. question_id is first so PostgreSQL
-- can also use the indexes for foreign-key checks when a question is changed
-- or deleted. tenant_id preserves the application query's tenant boundary,
-- and the selected parent id is covered as a non-searchable INCLUDE column.
--
-- Run during a low-write window. Building a regular PostgreSQL index blocks
-- writes to its table while allowing reads; lock_timeout makes the migration
-- fail instead of waiting indefinitely for a conflicting lock.
begin;

set local lock_timeout = '5s';

create index if not exists idx_attempt_answers_question_tenant_attempt
  on public.attempt_answers(question_id, tenant_id)
  include (attempt_id);

create index if not exists idx_practice_answers_question_tenant_session
  on public.practice_answers(question_id, tenant_id)
  include (session_id);

-- Both dropped indexes duplicate the left edge of the tables' unique
-- constraints: unique(attempt_id, question_id) and
-- unique(session_id, question_id). Removing them offsets the write/storage
-- cost of the two useful question-first indexes above.
drop index if exists public.idx_answers_attempt;
drop index if exists public.idx_practice_answers_session;

commit;
