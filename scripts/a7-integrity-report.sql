-- Release A7 post-load integrity report. Read-only; run on isolated staging.
-- Set the UTC beginning of the load-test window before including this file:
--   set arivupro.capacity_started_at = '2026-09-26T05:00:00Z';

begin transaction read only;

do $$
begin
  if nullif(current_setting('arivupro.capacity_started_at', true), '') is null then
    raise exception 'Set arivupro.capacity_started_at to the UTC load-test start time';
  end if;
end
$$;

-- Run shape: save this beside the HTTP reports.
with a7_window as (
  select current_setting('arivupro.capacity_started_at')::timestamptz as started_at
)
select 'quiz_attempts' as workload, status, count(*)::bigint as rows
from public.quiz_attempts, a7_window
where quiz_attempts.started_at >= a7_window.started_at
group by status
union all
select 'practice_sessions', status, count(*)::bigint
from public.practice_sessions, a7_window
where practice_sessions.started_at >= a7_window.started_at
group by status
order by workload, status;

-- Every result must be zero before A7 can be signed off.
with a7_window as (
  select current_setting('arivupro.capacity_started_at')::timestamptz as started_at
), quiz_answer_counts as (
  select attempt.id, attempt.status,
    jsonb_array_length(coalesce(attempt.question_snapshot, '[]'::jsonb)) as expected,
    count(answer.id)::integer as actual
  from public.quiz_attempts attempt
  cross join a7_window
  left join public.attempt_answers answer
    on answer.attempt_id = attempt.id and answer.tenant_id = attempt.tenant_id
  where attempt.started_at >= a7_window.started_at
  group by attempt.id, attempt.status, attempt.question_snapshot
), practice_answer_counts as (
  select session.id, session.status,
    jsonb_array_length(coalesce(session.question_snapshot, '[]'::jsonb)) as expected,
    count(answer.id)::integer as actual
  from public.practice_sessions session
  cross join a7_window
  left join public.practice_answers answer
    on answer.session_id = session.id and answer.tenant_id = session.tenant_id
  where session.started_at >= a7_window.started_at
  group by session.id, session.status, session.question_snapshot
), violations as (
  select 'graded_quiz_answer_count_mismatch' as check_name, count(*)::bigint as violations
  from quiz_answer_counts where status = 'graded' and actual <> expected
  union all
  select 'open_quiz_has_persisted_answers', count(*)::bigint
  from quiz_answer_counts where status = 'in_progress' and actual <> 0
  union all
  select 'graded_practice_answer_count_mismatch', count(*)::bigint
  from practice_answer_counts where status = 'graded' and actual <> expected
  union all
  select 'open_practice_has_persisted_answers', count(*)::bigint
  from practice_answer_counts where status = 'in_progress' and actual <> 0
  union all
  select 'cross_tenant_quiz_answers', count(*)::bigint
  from public.attempt_answers answer
  join public.quiz_attempts attempt on attempt.id = answer.attempt_id
  cross join a7_window
  where attempt.started_at >= a7_window.started_at
    and answer.tenant_id <> attempt.tenant_id
  union all
  select 'cross_tenant_practice_answers', count(*)::bigint
  from public.practice_answers answer
  join public.practice_sessions session on session.id = answer.session_id
  cross join a7_window
  where session.started_at >= a7_window.started_at
    and answer.tenant_id <> session.tenant_id
  union all
  select 'duplicate_quiz_answers', count(*)::bigint
  from (
    select answer.attempt_id, answer.question_id
    from public.attempt_answers answer
    join public.quiz_attempts attempt on attempt.id = answer.attempt_id
    cross join a7_window
    where attempt.started_at >= a7_window.started_at
    group by answer.attempt_id, answer.question_id having count(*) > 1
  ) duplicates
  union all
  select 'duplicate_practice_answers', count(*)::bigint
  from (
    select answer.session_id, answer.question_id
    from public.practice_answers answer
    join public.practice_sessions session on session.id = answer.session_id
    cross join a7_window
    where session.started_at >= a7_window.started_at
    group by answer.session_id, answer.question_id having count(*) > 1
  ) duplicates
)
select check_name, violations
from violations
order by check_name;

-- Queue recovery/pressure snapshot for the same run window.
with a7_window as (
  select current_setting('arivupro.capacity_started_at')::timestamptz as started_at
)
select status, count(*)::bigint as jobs,
  min(created_at) as oldest_created_at,
  max(extract(epoch from (now() - created_at))) filter (where status = 'queued') as oldest_queue_age_seconds,
  count(*) filter (
    where status = 'running' and lease_expires_at is not null and lease_expires_at < now()
  )::bigint as expired_running_leases
from public.faculty_jobs, a7_window
where faculty_jobs.created_at >= a7_window.started_at
group by status
order by status;

commit;
