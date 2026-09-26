-- Migration 69 — bounded keyset pages for Release A3.
-- Apply after migration 68 and before deploying the matching API code.
begin;

create index if not exists idx_quizsets_tenant_creator_status_created_id
  on public.quiz_sets(tenant_id, created_by, status, created_at desc, id desc);
create index if not exists idx_quizsets_tenant_subject_status_created_id
  on public.quiz_sets(tenant_id, subject_id, status, created_at desc, id desc);
create index if not exists idx_quizsets_tenant_creator_status_published_id
  on public.quiz_sets(
    tenant_id, created_by, status,
    (coalesce(published_at, created_at)) desc, id desc
  );
create index if not exists idx_quizsets_tenant_subject_status_published_id
  on public.quiz_sets(
    tenant_id, subject_id, status,
    (coalesce(published_at, created_at)) desc, id desc
  );
create index if not exists idx_documents_tenant_uploader_created_id
  on public.documents(tenant_id, uploaded_by, created_at desc, id desc);
create index if not exists idx_attempts_tenant_student_status_submitted_id
  on public.quiz_attempts(tenant_id, student_id, status, submitted_at desc, id desc);
create index if not exists idx_practice_tenant_student_status_submitted_id
  on public.practice_sessions(tenant_id, student_id, status, submitted_at desc, id desc);

create or replace function public.teacher_published_quiz_metrics_page(
  p_tenant uuid,
  p_teacher uuid,
  p_limit integer,
  p_before_at timestamptz default null,
  p_before_id uuid default null,
  p_subject uuid default null,
  p_search text default null
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select profile.id
  from public.profiles profile
  where profile.id = p_teacher
    and profile.tenant_id = p_tenant
    and profile.role = 'teacher'
), assigned_subjects as (
  select subject.id, subject.name, subject.course_id
  from public.teacher_subjects assignment
  join actor on true
  join public.subjects subject
    on subject.id = assignment.subject_id
   and subject.tenant_id = p_tenant
  where assignment.tenant_id = p_tenant
    and assignment.teacher_id = p_teacher
), published_sets as materialized (
  select quiz.id, quiz.title, quiz.subject_id, quiz.published_at,
    coalesce(quiz.published_at, quiz.created_at) as cursor_at,
    subject.name as subject_name, subject.course_id
  from public.quiz_sets quiz
  join assigned_subjects subject on subject.id = quiz.subject_id
  where quiz.tenant_id = p_tenant
    and quiz.created_by = p_teacher
    and quiz.status = 'published'
    and (p_subject is null or quiz.subject_id = p_subject)
    and (nullif(trim(p_search), '') is null or quiz.title ilike '%' || trim(p_search) || '%')
    and (
      p_before_at is null
      or (coalesce(quiz.published_at, quiz.created_at), quiz.id) < (p_before_at, p_before_id)
    )
  order by coalesce(quiz.published_at, quiz.created_at) desc, quiz.id desc
  limit least(greatest(p_limit, 1), 101)
), eligible as (
  select subject.course_id, count(distinct enrollment.profile_id)::int as students
  from (select distinct course_id from published_sets) subject
  left join public.enrollments enrollment
    on enrollment.course_id = subject.course_id
   and enrollment.tenant_id = p_tenant
  group by subject.course_id
), valid_attempts as (
  select quiz.id as quiz_set_id, attempt.student_id, attempt.submitted_at,
    round(
      least(greatest(coalesce(attempt.total_score, 0), 0), variant.total_marks)
      / variant.total_marks * 100,
      1
    )::numeric as accuracy
  from published_sets quiz
  join public.quiz_variants variant
    on variant.quiz_set_id = quiz.id
   and variant.tenant_id = p_tenant
   and variant.total_marks > 0
  join public.quiz_attempts attempt
    on attempt.variant_id = variant.id
   and attempt.tenant_id = p_tenant
   and attempt.status = 'graded'
  join public.enrollments enrollment
    on enrollment.tenant_id = p_tenant
   and enrollment.course_id = quiz.course_id
   and enrollment.profile_id = attempt.student_id
), attempt_counts as (
  select attempt.quiz_set_id,
    count(*)::int as total_attempts,
    count(distinct attempt.student_id)::int as completed_students,
    round(avg(attempt.accuracy), 1) as average_accuracy,
    max(attempt.accuracy) as highest_accuracy,
    min(attempt.accuracy) as lowest_accuracy,
    max(attempt.submitted_at) as last_activity
  from valid_attempts attempt
  group by attempt.quiz_set_id
)
select jsonb_build_object(
  'quizzes', coalesce(jsonb_agg(jsonb_build_object(
    'id', quiz.id,
    'title', quiz.title,
    'subject_id', quiz.subject_id,
    'subject', quiz.subject_name,
    'published_at', quiz.published_at,
    '_cursor_at', quiz.cursor_at,
    'eligible_students', coalesce(eligible.students, 0),
    'completed_students', coalesce(attempts.completed_students, 0),
    'not_started_students', greatest(
      coalesce(eligible.students, 0) - coalesce(attempts.completed_students, 0), 0
    ),
    'total_attempts', coalesce(attempts.total_attempts, 0),
    'average_accuracy', coalesce(attempts.average_accuracy, 0),
    'highest_accuracy', coalesce(attempts.highest_accuracy, 0),
    'lowest_accuracy', coalesce(attempts.lowest_accuracy, 0),
    'last_activity', attempts.last_activity
  ) order by quiz.cursor_at desc, quiz.id desc), '[]'::jsonb)
)
from published_sets quiz
left join eligible on eligible.course_id = quiz.course_id
left join attempt_counts attempts on attempts.quiz_set_id = quiz.id;
$$;

create or replace function public.student_attempt_history_page(
  p_tenant uuid,
  p_student uuid,
  p_limit integer,
  p_before_at timestamptz default null,
  p_before_id uuid default null,
  p_source text default 'all',
  p_subject uuid default null,
  p_chapter uuid default null
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select profile.id
  from public.profiles profile
  where profile.id = p_student
    and profile.tenant_id = p_tenant
    and profile.role = 'student'
), history as (
  select attempt.id, quiz.title as quiz_title, attempt.variant_id,
    variant.variant_type, quiz.subject_id, quiz.chapter_id,
    attempt.total_score, variant.total_marks as max_score,
    attempt.submitted_at, 'quiz'::text as source
  from public.quiz_attempts attempt
  join actor on true
  join public.quiz_variants variant
    on variant.id = attempt.variant_id and variant.tenant_id = p_tenant
  join public.quiz_sets quiz
    on quiz.id = variant.quiz_set_id and quiz.tenant_id = p_tenant
  where attempt.tenant_id = p_tenant
    and attempt.student_id = p_student
    and attempt.status = 'graded'
    and attempt.submitted_at is not null
    and p_source in ('all', 'quiz')
  union all
  select session.id,
    initcap(replace(coalesce(session.mode, 'practice'), '_', ' ')) || ' practice',
    null::uuid, session.mode,
    coalesce(session.subject_id, chapter.subject_id), session.chapter_id,
    session.total_score, session.max_score, session.submitted_at, 'practice'::text
  from public.practice_sessions session
  join actor on true
  left join public.chapters chapter
    on chapter.id = session.chapter_id and chapter.tenant_id = p_tenant
  where session.tenant_id = p_tenant
    and session.student_id = p_student
    and session.status = 'graded'
    and session.mode <> 'challenge'
    and session.submitted_at is not null
    and p_source in ('all', 'practice')
), filtered as (
  select * from history
  where (p_subject is null or subject_id = p_subject)
    and (p_chapter is null or chapter_id = p_chapter)
    and (p_before_at is null or (submitted_at, id) < (p_before_at, p_before_id))
  order by submitted_at desc, id desc
  limit least(greatest(p_limit, 1), 101)
)
select coalesce(jsonb_agg(jsonb_build_object(
  'attempt_id', id,
  'quiz_title', quiz_title,
  'variant_id', variant_id,
  'variant_type', variant_type,
  'subject_id', subject_id,
  'chapter_id', chapter_id,
  'total_score', total_score,
  'max_score', max_score,
  'submitted_at', submitted_at,
  'source', source,
  '_cursor_at', submitted_at
) order by submitted_at desc, id desc), '[]'::jsonb)
from filtered;
$$;

create or replace function public.student_quiz_catalog_page(
  p_tenant uuid,
  p_student uuid,
  p_limit integer,
  p_attempt_limit integer,
  p_batches_enabled boolean,
  p_before_at timestamptz default null,
  p_before_id uuid default null,
  p_subject uuid default null,
  p_chapter uuid default null,
  p_assignment text default 'all',
  p_search text default null
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select profile.id
  from public.profiles profile
  where profile.id = p_student
    and profile.tenant_id = p_tenant
    and profile.role = 'student'
), enrolled_subjects as (
  select subject.id
  from public.enrollments enrollment
  join actor on true
  join public.subjects subject
    on subject.tenant_id = p_tenant
   and subject.course_id = enrollment.course_id
   and (
     enrollment.course_level_id is null
     or subject.course_level_id = enrollment.course_level_id
   )
  where enrollment.tenant_id = p_tenant
    and enrollment.profile_id = p_student
), accessible as materialized (
  select quiz.id, quiz.title,
    coalesce(quiz.published_at, quiz.created_at) as cursor_at, quiz.published_at,
    quiz.subject_id, quiz.chapter_id, subject.name as subject_name,
    chapter.name as chapter_name
  from public.quiz_sets quiz
  join enrolled_subjects enrolled on enrolled.id = quiz.subject_id
  join public.subjects subject
    on subject.id = quiz.subject_id and subject.tenant_id = p_tenant
  left join public.chapters chapter
    on chapter.id = quiz.chapter_id and chapter.tenant_id = p_tenant
  where quiz.tenant_id = p_tenant
    and quiz.status = 'published'
    and (p_subject is null or quiz.subject_id = p_subject)
    and (p_chapter is null or quiz.chapter_id = p_chapter)
    and (nullif(trim(p_search), '') is null or quiz.title ilike '%' || trim(p_search) || '%')
    and (
      not p_batches_enabled
      or (
        p_assignment in ('all', 'course')
        and coalesce(quiz.audience_mode, 'legacy_course') = 'legacy_course'
      )
      or (
        p_assignment in ('all', 'assigned')
        and quiz.audience_mode = 'assigned_batches'
        and exists (
          select 1
          from public.quiz_assignments assignment
          join public.batch_memberships membership
            on membership.tenant_id = p_tenant
           and membership.batch_id = assignment.batch_id
           and membership.profile_id = p_student
           and membership.active
           and (membership.valid_from is null or membership.valid_from <= current_date)
           and (membership.valid_to is null or membership.valid_to >= current_date)
          where assignment.tenant_id = p_tenant
            and assignment.quiz_set_id = quiz.id
            and assignment.status = 'active'
            and (assignment.available_from is null or assignment.available_from <= now())
            and (assignment.available_to is null or assignment.available_to >= now())
        )
      )
    )
    and (p_before_at is null or (coalesce(quiz.published_at, quiz.created_at), quiz.id) < (p_before_at, p_before_id))
    and exists (
      select 1
      from public.quiz_variants variant
      join public.quiz_variant_questions link
        on link.tenant_id = p_tenant and link.variant_id = variant.id
      join public.questions question
        on question.tenant_id = p_tenant
       and question.id = link.question_id
       and question.review_status = 'approved'
      where variant.tenant_id = p_tenant and variant.quiz_set_id = quiz.id
    )
  order by coalesce(quiz.published_at, quiz.created_at) desc, quiz.id desc
  limit least(greatest(p_limit, 1), 101)
), variant_rows as (
  select quiz.id as quiz_set_id, variant.id, variant.variant_type,
    variant.total_marks, variant.time_limit_minutes,
    count(question.id)::int as question_count,
    ceil(sum(case question.type
      when 'true_false' then 45
      when 'mcq_single' then 60
      when 'fill_blank' then 75
      when 'mcq_multi' then 90
      when 'numerical' then 120
      else 90
    end)::numeric / 60)::int as derived_minutes
  from accessible quiz
  join public.quiz_variants variant
    on variant.tenant_id = p_tenant and variant.quiz_set_id = quiz.id
  join public.quiz_variant_questions link
    on link.tenant_id = p_tenant and link.variant_id = variant.id
  join public.questions question
    on question.tenant_id = p_tenant
   and question.id = link.question_id
   and question.review_status = 'approved'
  group by quiz.id, variant.id, variant.variant_type,
    variant.total_marks, variant.time_limit_minutes
), attempt_rows as (
  select variant.id as variant_id,
    count(attempt.id)::int as attempt_count,
    max(attempt.total_score) filter (where attempt.status = 'graded') as best_score,
    count(attempt.id) filter (where attempt.status = 'graded')::int as graded_count
  from variant_rows variant
  left join public.quiz_attempts attempt
    on attempt.tenant_id = p_tenant
   and attempt.variant_id = variant.id
   and attempt.student_id = p_student
  group by variant.id
), variants_by_quiz as (
  select variant.quiz_set_id, jsonb_agg(jsonb_build_object(
    'id', variant.id,
    'variant_type', variant.variant_type,
    'total_marks', variant.total_marks,
    'time_limit_minutes', coalesce(variant.time_limit_minutes, variant.derived_minutes),
    'question_count', variant.question_count,
    'attempted', attempts.graded_count > 0,
    'attempt_count', attempts.attempt_count,
    'attempt_limit', p_attempt_limit,
    'attempts_remaining', greatest(p_attempt_limit - attempts.attempt_count, 0),
    'best_pct', case
      when attempts.graded_count > 0 and variant.total_marks > 0
      then least(100, greatest(0, round(attempts.best_score / variant.total_marks * 100)))::int
      else null
    end
  ) order by variant.id) as variants
  from variant_rows variant
  join attempt_rows attempts on attempts.variant_id = variant.id
  group by variant.quiz_set_id
)
select coalesce(jsonb_agg(jsonb_build_object(
  'id', quiz.id,
  'title', quiz.title,
  'published_at', quiz.published_at,
  'subject_id', quiz.subject_id,
  'chapter_id', quiz.chapter_id,
  'subject_name', quiz.subject_name,
  'chapter_name', quiz.chapter_name,
  'variants', variants.variants,
  '_cursor_at', quiz.cursor_at
) order by quiz.cursor_at desc, quiz.id desc), '[]'::jsonb)
from accessible quiz
join variants_by_quiz variants on variants.quiz_set_id = quiz.id;
$$;

revoke all on function public.teacher_published_quiz_metrics_page(
  uuid, uuid, integer, timestamptz, uuid, uuid, text
) from public, anon, authenticated;
revoke all on function public.student_attempt_history_page(
  uuid, uuid, integer, timestamptz, uuid, text, uuid, uuid
) from public, anon, authenticated;
revoke all on function public.student_quiz_catalog_page(
  uuid, uuid, integer, integer, boolean, timestamptz, uuid, uuid, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.teacher_published_quiz_metrics_page(
  uuid, uuid, integer, timestamptz, uuid, uuid, text
) to service_role;
grant execute on function public.student_attempt_history_page(
  uuid, uuid, integer, timestamptz, uuid, text, uuid, uuid
) to service_role;
grant execute on function public.student_quiz_catalog_page(
  uuid, uuid, integer, integer, boolean, timestamptz, uuid, uuid, uuid, text, text
) to service_role;

commit;
notify pgrst, 'reload schema';
