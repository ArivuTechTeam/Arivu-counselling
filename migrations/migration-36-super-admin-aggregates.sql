-- Migration 36 — scalable super-admin analytics
-- Apply after migration 35.
--
-- These functions aggregate cross-tenant platform data inside PostgreSQL so
-- the API does not download every question, event, attempt, and profile.
-- They use the caller's privileges (service_role from the backend), are not
-- callable by browser roles, and do not weaken table RLS.

begin;

create or replace function public.platform_overview_metrics()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with profile_counts as (
  select tenant_id,
    count(*) filter (where role = 'teacher')::int as teachers,
    count(*) filter (where role = 'student')::int as students,
    count(*) filter (where role = 'institution_admin')::int as admins
  from public.profiles
  group by tenant_id
), quiz_counts as (
  select tenant_id,
    count(*)::int as quiz_sets,
    count(*) filter (where status = 'published')::int as published
  from public.quiz_sets
  group by tenant_id
), graded_attempts as (
  select a.tenant_id, a.submitted_at,
    least(greatest(coalesce(a.total_score, 0), 0), v.total_marks)::numeric as score,
    v.total_marks::numeric as maximum
  from public.quiz_attempts a
  join public.quiz_variants v on v.id = a.variant_id
  where a.status = 'graded' and v.total_marks > 0
), attempt_counts as (
  select tenant_id, count(*)::int as attempts,
    coalesce(sum(score), 0) as score_sum,
    coalesce(sum(maximum), 0) as maximum_sum
  from graded_attempts
  group by tenant_id
), institution_rows as (
  select t.id, t.name, t.subdomain, t.created_at, t.plan_tier, t.is_active,
    coalesce(p.teachers, 0) as teachers,
    coalesce(p.students, 0) as students,
    coalesce(p.admins, 0) as admins,
    coalesce(q.quiz_sets, 0) as quiz_sets,
    coalesce(q.published, 0) as published,
    coalesce(a.attempts, 0) as attempts,
    case when coalesce(a.maximum_sum, 0) > 0
      then round(a.score_sum / a.maximum_sum * 100)::int else 0 end as accuracy
  from public.tenants t
  left join profile_counts p on p.tenant_id = t.id
  left join quiz_counts q on q.tenant_id = t.id
  left join attempt_counts a on a.tenant_id = t.id
), question_counts as (
  select
    count(*)::int as total,
    count(*) filter (where review_status = 'pending_review')::int as pending_review,
    count(*) filter (where review_status = 'approved')::int as approved,
    count(*) filter (where review_status = 'rejected')::int as rejected,
    count(*) filter (where review_status = 'needs_edit')::int as needs_edit
  from public.questions
), activity_days as (
  select day::date
  from generate_series(current_date - 13, current_date, interval '1 day') day
), activity as (
  select d.day, count(g.submitted_at)::int as attempts
  from activity_days d
  left join graded_attempts g on g.submitted_at::date = d.day
  group by d.day
  order by d.day
), totals as (
  select
    (select count(*)::int from public.tenants) as institutions,
    (select count(*)::int from public.tenants where is_active) as active_institutions,
    (select count(*)::int from public.profiles where role = 'teacher') as teachers,
    (select count(*)::int from public.profiles where role = 'student') as students,
    (select count(*)::int from public.profiles where role = 'institution_admin') as admins,
    (select count(*)::int from public.quiz_sets) as quiz_sets,
    (select count(*)::int from public.quiz_sets where status = 'published') as published_quizzes,
    (select count(*)::int from public.documents) as documents,
    (select count(*)::int from graded_attempts) as attempts,
    (select case when coalesce(sum(maximum), 0) > 0
      then round(sum(score) / sum(maximum) * 100)::int else 0 end from graded_attempts) as accuracy
)
select jsonb_build_object(
  'institutions', t.institutions,
  'active_institutions', t.active_institutions,
  'teachers', t.teachers,
  'students', t.students,
  'admins', t.admins,
  'quiz_sets', t.quiz_sets,
  'published_quizzes', t.published_quizzes,
  'questions', q.total,
  'documents', t.documents,
  'attempts', t.attempts,
  'accuracy', t.accuracy,
  'approval_rate', case when (q.approved + q.rejected + q.needs_edit) > 0
    then round(q.approved::numeric / (q.approved + q.rejected + q.needs_edit) * 100)::int
    else 0 end,
  'pipeline', jsonb_build_object(
    'pending_review', q.pending_review,
    'approved', q.approved,
    'rejected', q.rejected,
    'needs_edit', q.needs_edit
  ),
  'activity', coalesce((
    select jsonb_agg(jsonb_build_object(
      'date', to_char(day, 'MM-DD'), 'attempts', attempts
    ) order by day) from activity
  ), '[]'::jsonb),
  'institutions_table', coalesce((
    select jsonb_agg(to_jsonb(i) order by (i.students + i.teachers) desc, i.name)
    from institution_rows i
  ), '[]'::jsonb)
)
from totals t cross join question_counts q;
$$;

create or replace function public.platform_question_bank_metrics()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with question_rows as (
  select q.id, q.difficulty, q.type::text as type,
    q.review_status::text as review_status,
    ch.id as chapter_id, s.id as subject_id, c.id as course_id,
    c.name as course, t.name as tenant
  from public.questions q
  left join public.chapters ch on ch.id = q.chapter_id
  left join public.subjects s on s.id = ch.subject_id
  left join public.courses c on c.id = s.course_id
  left join public.tenants t on t.id = c.tenant_id
), course_counts as (
  select course_id, max(course) as course, max(tenant) as tenant,
    count(*)::int as questions,
    count(distinct subject_id)::int as subjects,
    count(distinct chapter_id)::int as chapters,
    count(*) filter (where review_status = 'pending_review')::int as pending_review,
    count(*) filter (where review_status = 'approved')::int as approved,
    count(*) filter (where review_status = 'rejected')::int as rejected,
    count(*) filter (where review_status = 'needs_edit')::int as needs_edit
  from question_rows
  where course_id is not null
  group by course_id
)
select jsonb_build_object(
  'total', (select count(*)::int from question_rows),
  'uncategorised', (select count(*)::int from question_rows where course_id is null),
  'courses', coalesce((
    select jsonb_agg(
      jsonb_build_object(
        'course', cc.course,
        'tenant', cc.tenant,
        'questions', cc.questions,
        'subjects', cc.subjects,
        'chapters', cc.chapters,
        'difficulty', coalesce((
          select jsonb_object_agg(bucket, amount)
          from (
            select coalesce(qr.difficulty, 'unspecified') as bucket, count(*)::int as amount
            from question_rows qr where qr.course_id = cc.course_id
            group by coalesce(qr.difficulty, 'unspecified')
          ) grouped_difficulty
        ), '{}'::jsonb),
        'types', coalesce((
          select jsonb_object_agg(bucket, amount)
          from (
            select qr.type as bucket, count(*)::int as amount
            from question_rows qr where qr.course_id = cc.course_id
            group by qr.type
          ) grouped_types
        ), '{}'::jsonb),
        'review_status', jsonb_build_object(
          'pending_review', cc.pending_review,
          'approved', cc.approved,
          'rejected', cc.rejected,
          'needs_edit', cc.needs_edit
        )
      ) order by cc.questions desc, cc.course
    ) from course_counts cc
  ), '[]'::jsonb)
);
$$;

create or replace function public.platform_ai_monitoring_metrics()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with ai_questions as (
  select id, type::text as type, coalesce(difficulty, 'unspecified') as difficulty,
    review_status::text as review_status, created_at
  from public.questions where source = 'ai_generated'
), question_summary as (
  select count(*)::int as total,
    count(*) filter (where review_status = 'pending_review')::int as pending_review,
    count(*) filter (where review_status = 'approved')::int as approved,
    count(*) filter (where review_status = 'rejected')::int as rejected,
    count(*) filter (where review_status = 'needs_edit')::int as needs_edit
  from ai_questions
), type_counts as (
  select type, count(*)::int as total,
    count(*) filter (where review_status = 'approved')::int as approved
  from ai_questions group by type
), difficulty_counts as (
  select difficulty, count(*)::int as total,
    count(*) filter (where review_status = 'approved')::int as approved
  from ai_questions group by difficulty
), days as (
  select day::date from generate_series(current_date - 13, current_date, interval '1 day') day
), volume as (
  select d.day, count(q.id)::int as generated
  from days d left join ai_questions q on q.created_at::date = d.day
  group by d.day order by d.day
), monitored_events as (
  select * from public.events
  where event_type in (
    'question.generated', 'question.edited', 'question.approved',
    'question.rejected', 'question.regenerated', 'quiz.published',
    'generation.failed'
  )
), generated as (
  select distinct on (subject_id) subject_id,
    coalesce(metadata->>'type', 'unknown') as type, created_at
  from monitored_events
  where event_type = 'question.generated' and subject_id is not null
  order by subject_id, created_at desc, id desc
), edited as (
  select distinct subject_id
  from monitored_events
  where event_type = 'question.edited' and subject_id is not null
), decisions as (
  select distinct on (subject_id) subject_id, event_type, created_at
  from monitored_events
  where event_type in ('question.approved', 'question.rejected')
    and subject_id is not null
  order by subject_id, created_at desc, id desc
), signal_rows as (
  select g.subject_id, g.type, d.event_type, d.created_at as decided_at,
    (e.subject_id is not null) as was_edited
  from generated g
  left join decisions d on d.subject_id = g.subject_id
  left join edited e on e.subject_id = g.subject_id
), signal_summary as (
  select count(*)::int as generated,
    count(*) filter (where event_type is not null)::int as reviewed,
    count(*) filter (where event_type = 'question.approved')::int as approved,
    count(*) filter (where event_type = 'question.rejected')::int as rejected,
    count(*) filter (where event_type = 'question.approved' and not was_edited)::int as kept_as_is,
    count(*) filter (where event_type is null)::int as pending
  from signal_rows
), signal_types as (
  select type, count(*)::int as generated,
    count(*) filter (where event_type = 'question.approved')::int as approved,
    count(*) filter (where event_type = 'question.approved' and not was_edited)::int as kept_as_is
  from signal_rows group by type
), edited_fields as (
  select field, count(*)::int as amount
  from monitored_events e
  cross join lateral jsonb_array_elements_text(
    case when jsonb_typeof(e.metadata->'edited_fields') = 'array'
      then e.metadata->'edited_fields' else '[]'::jsonb end
  ) as fields(field)
  where e.event_type = 'question.edited'
  group by field
), trend as (
  select
    count(*) filter (where event_type = 'question.approved' and decided_at::date >= current_date - 7)::int as approved_last7,
    count(*) filter (where event_type = 'question.approved' and decided_at::date >= current_date - 7 and not was_edited)::int as kept_last7,
    count(*) filter (where event_type = 'question.approved' and decided_at::date >= current_date - 14 and decided_at::date < current_date - 7)::int as approved_prev7,
    count(*) filter (where event_type = 'question.approved' and decided_at::date >= current_date - 14 and decided_at::date < current_date - 7 and not was_edited)::int as kept_prev7
  from signal_rows
), base as (
  select q.*, s.generated as signal_generated, s.reviewed as signal_reviewed,
    s.approved as signal_approved, s.rejected as signal_rejected,
    s.kept_as_is, s.pending as signal_pending,
    t.approved_last7, t.kept_last7, t.approved_prev7, t.kept_prev7
  from question_summary q cross join signal_summary s cross join trend t
)
select jsonb_build_object(
  'total_generated', b.total,
  'approval_rate', case when (b.approved + b.rejected + b.needs_edit) > 0
    then round(b.approved::numeric / (b.approved + b.rejected + b.needs_edit) * 100)::int else 0 end,
  'published_quizzes', (select count(*)::int from public.quiz_sets where status = 'published'),
  'failures_14d', (select count(*)::int from monitored_events where event_type = 'generation.failed' and created_at::date >= current_date - 14),
  'pipeline', jsonb_build_object(
    'pending_review', b.pending_review, 'approved', b.approved,
    'rejected', b.rejected, 'needs_edit', b.needs_edit
  ),
  'by_type', coalesce((select jsonb_agg(jsonb_build_object(
    'type', type, 'total', total, 'approved', approved,
    'approval', case when total > 0 then round(approved::numeric / total * 100)::int else 0 end
  ) order by total desc, type) from type_counts), '[]'::jsonb),
  'by_difficulty', coalesce((select jsonb_object_agg(difficulty, total) from difficulty_counts), '{}'::jsonb),
  'difficulty_quality', coalesce((select jsonb_agg(jsonb_build_object(
    'difficulty', difficulty, 'total', total, 'approved', approved,
    'approval', case when total > 0 then round(approved::numeric / total * 100)::int else 0 end
  ) order by total desc, difficulty) from difficulty_counts), '[]'::jsonb),
  'volume', coalesce((select jsonb_agg(jsonb_build_object(
    'date', to_char(day, 'MM-DD'), 'generated', generated
  ) order by day) from volume), '[]'::jsonb),
  'trend', jsonb_build_object(
    'keep_rate_last7', case when b.approved_last7 > 0 then round(b.kept_last7::numeric / b.approved_last7 * 100)::int else 0 end,
    'keep_rate_prev7', case when b.approved_prev7 > 0 then round(b.kept_prev7::numeric / b.approved_prev7 * 100)::int else 0 end,
    'keep_rate_delta',
      (case when b.approved_last7 > 0 then round(b.kept_last7::numeric / b.approved_last7 * 100)::int else 0 end) -
      (case when b.approved_prev7 > 0 then round(b.kept_prev7::numeric / b.approved_prev7 * 100)::int else 0 end),
    'approved_last7', b.approved_last7,
    'approved_prev7', b.approved_prev7,
    'has_trend', (b.approved_last7 + b.approved_prev7) > 0
  ),
  'funnel', jsonb_build_array(
    jsonb_build_object('stage', 'Generated', 'count', b.total),
    jsonb_build_object('stage', 'Reviewed', 'count', b.approved + b.rejected + b.needs_edit),
    jsonb_build_object('stage', 'Approved', 'count', b.approved),
    jsonb_build_object('stage', 'Kept as-is', 'count', b.kept_as_is)
  ),
  'signals', jsonb_build_object(
    'measured_from', (select min(created_at)::date::text from monitored_events),
    'generated', b.signal_generated,
    'reviewed', b.signal_reviewed,
    'approved', b.signal_approved,
    'rejected', b.signal_rejected,
    'kept_as_is', b.kept_as_is,
    'approved_after_edit', b.signal_approved - b.kept_as_is,
    'regenerated', (select count(*)::int from monitored_events where event_type = 'question.regenerated'),
    'pending', b.signal_pending,
    'approval_rate', case when b.signal_reviewed > 0 then round(b.signal_approved::numeric / b.signal_reviewed * 100)::int else 0 end,
    'kept_as_is_rate', case when b.signal_approved > 0 then round(b.kept_as_is::numeric / b.signal_approved * 100)::int else 0 end,
    'by_type', coalesce((select jsonb_agg(jsonb_build_object(
      'type', type, 'generated', generated, 'approved', approved,
      'kept_as_is', kept_as_is,
      'kept_rate', case when approved > 0 then round(kept_as_is::numeric / approved * 100)::int else 0 end
    ) order by generated desc, type) from signal_types), '[]'::jsonb),
    'most_edited_fields', coalesce((select jsonb_agg(jsonb_build_object(
      'field', field, 'count', amount
    ) order by amount desc, field) from (select * from edited_fields order by amount desc, field limit 6) top_fields), '[]'::jsonb)
  )
)
from base b;
$$;

revoke all on function public.platform_overview_metrics()
  from public, anon, authenticated;
revoke all on function public.platform_question_bank_metrics()
  from public, anon, authenticated;
revoke all on function public.platform_ai_monitoring_metrics()
  from public, anon, authenticated;

grant execute on function public.platform_overview_metrics() to service_role;
grant execute on function public.platform_question_bank_metrics() to service_role;
grant execute on function public.platform_ai_monitoring_metrics() to service_role;

commit;
