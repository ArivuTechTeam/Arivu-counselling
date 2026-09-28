-- Migration 68 — tenant-scoped teacher dashboard aggregates (Release A2).
-- Apply after migration 67 and before deploying the matching API code.
--
-- These functions keep large aggregation work inside PostgreSQL. They execute
-- with the service-role caller's privileges, repeat tenant/actor/current-
-- assignment scope internally, and are unavailable to browser roles.
begin;

create or replace function public.teacher_class_overview_metrics(
  p_tenant uuid,
  p_teacher uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select p.id
  from public.profiles p
  where p.id = p_teacher
    and p.tenant_id = p_tenant
    and p.role = 'teacher'
), assigned_subjects as (
  select ts.subject_id
  from public.teacher_subjects ts
  join actor on true
  where ts.tenant_id = p_tenant
    and ts.teacher_id = p_teacher
), owned_sets as (
  select qs.id, qs.title, qs.status
  from public.quiz_sets qs
  join assigned_subjects assigned on assigned.subject_id = qs.subject_id
  where qs.tenant_id = p_tenant
    and qs.created_by = p_teacher
), variants as (
  select v.id, v.quiz_set_id, v.total_marks
  from public.quiz_variants v
  join owned_sets qs on qs.id = v.quiz_set_id
  where v.tenant_id = p_tenant
), graded_attempts as (
  select a.id, a.student_id, a.variant_id, a.total_score, a.submitted_at,
    v.quiz_set_id, v.total_marks
  from public.quiz_attempts a
  join variants v on v.id = a.variant_id
  where a.tenant_id = p_tenant
    and a.status = 'graded'
), valid_attempts as (
  select a.*,
    least(greatest(coalesce(a.total_score, 0), 0), a.total_marks)::numeric as bounded_score,
    (least(greatest(coalesce(a.total_score, 0), 0), a.total_marks)
      / a.total_marks * 100)::numeric as accuracy
  from graded_attempts a
  where a.total_marks > 0
), quiz_rows as (
  select qs.id as set_id, qs.title,
    round(sum(a.bounded_score) / sum(a.total_marks) * 100)::int as accuracy,
    count(*)::int as attempts
  from valid_attempts a
  join owned_sets qs on qs.id = a.quiz_set_id
  group by qs.id, qs.title
), student_totals as (
  select a.student_id,
    sum(a.bounded_score)::numeric as score_sum,
    sum(a.total_marks)::numeric as maximum_sum,
    count(*)::int as attempts
  from valid_attempts a
  group by a.student_id
), student_rows as (
  select totals.student_id,
    coalesce(nullif(profile.full_name, ''), 'Student') as name,
    upper(
      left(coalesce(nullif(profile.full_name, ''), 'Student'), 1)
      || case
        when position(' ' in trim(coalesce(nullif(profile.full_name, ''), 'Student'))) > 0
        then left(split_part(trim(coalesce(nullif(profile.full_name, ''), 'Student')), ' ', 2), 1)
        else ''
      end
    ) as initials,
    round(totals.score_sum / totals.maximum_sum * 100)::int as accuracy,
    totals.attempts
  from student_totals totals
  left join public.profiles profile
    on profile.id = totals.student_id
   and profile.tenant_id = p_tenant
   and profile.role = 'student'
), linked_questions as (
  select distinct q.id, q.review_status
  from variants v
  join public.quiz_variant_questions link
    on link.variant_id = v.id
   and link.tenant_id = p_tenant
  join public.questions q
    on q.id = link.question_id
   and q.tenant_id = p_tenant
), pipeline as (
  select
    count(*) filter (where review_status = 'pending_review')::int as pending_review,
    count(*) filter (where review_status = 'approved')::int as approved,
    count(*) filter (where review_status = 'rejected')::int as rejected,
    count(*) filter (where review_status = 'needs_edit')::int as needs_edit
  from linked_questions
), activity_days as (
  select day::date
  from generate_series(current_date - 13, current_date, interval '1 day') day
), activity as (
  select days.day,
    count(attempts.id)::int as amount
  from activity_days days
  left join valid_attempts attempts
    on (attempts.submitted_at at time zone 'UTC')::date = days.day
  group by days.day
), content as (
  select
    (select count(*)::int
     from public.documents document
     join actor on true
     where document.tenant_id = p_tenant
       and document.uploaded_by = p_teacher) as documents,
    count(*)::int as quiz_sets,
    count(*) filter (where status = 'published')::int as published,
    count(*) filter (where status = 'draft')::int as drafts
  from owned_sets
), totals as (
  select
    coalesce(round(sum(bounded_score) / nullif(sum(total_marks), 0) * 100)::int, 0) as class_accuracy,
    count(*)::int as scored_attempts
  from valid_attempts
)
select jsonb_build_object(
  'class_accuracy', totals.class_accuracy,
  'students', (select count(*)::int from student_rows),
  'at_risk', (select count(*)::int from student_rows where accuracy < 60),
  'total_attempts', (select count(*)::int from graded_attempts),
  'accuracy_by_quiz', coalesce((
    select jsonb_agg(jsonb_build_object(
      'set_id', row.set_id,
      'title', row.title,
      'accuracy', row.accuracy,
      'attempts', row.attempts
    ) order by row.attempts desc, row.set_id)
    from quiz_rows row
  ), '[]'::jsonb),
  'needs_attention', coalesce((
    select jsonb_agg(jsonb_build_object(
      'name', row.name,
      'initials', row.initials,
      'accuracy', row.accuracy,
      'note', row.attempts::text || ' test'
        || case when row.attempts = 1 then '' else 's' end
        || ' · ' || row.accuracy::text || '% avg'
    ) order by row.accuracy, row.student_id)
    from (
      select * from student_rows
      where accuracy < 60
      order by accuracy, student_id
      limit 6
    ) row
  ), '[]'::jsonb),
  'top_performers', coalesce((
    select jsonb_agg(jsonb_build_object(
      'name', row.name,
      'initials', row.initials,
      'accuracy', row.accuracy,
      'note', row.attempts::text || ' test'
        || case when row.attempts = 1 then '' else 's' end
        || ' · ' || row.accuracy::text || '% avg'
    ) order by row.accuracy desc, row.student_id)
    from (
      select * from student_rows
      order by accuracy desc, student_id
      limit 5
    ) row
  ), '[]'::jsonb),
  'pipeline', jsonb_build_object(
    'pending_review', pipeline.pending_review,
    'approved', pipeline.approved,
    'rejected', pipeline.rejected,
    'needs_edit', pipeline.needs_edit
  ),
  'activity_trend', coalesce((
    select jsonb_agg(jsonb_build_object(
      'date', to_char(day, 'YYYY-MM-DD'),
      'count', amount
    ) order by day)
    from activity
  ), '[]'::jsonb),
  'score_distribution', jsonb_build_array(
    jsonb_build_object('label', '0–39', 'count', (select count(*)::int from valid_attempts where accuracy >= 0 and accuracy < 40)),
    jsonb_build_object('label', '40–59', 'count', (select count(*)::int from valid_attempts where accuracy >= 40 and accuracy < 60)),
    jsonb_build_object('label', '60–79', 'count', (select count(*)::int from valid_attempts where accuracy >= 60 and accuracy < 80)),
    jsonb_build_object('label', '80–100', 'count', (select count(*)::int from valid_attempts where accuracy >= 80 and accuracy < 101))
  ),
  'content', jsonb_build_object(
    'documents', content.documents,
    'quiz_sets', content.quiz_sets,
    'published', content.published,
    'drafts', content.drafts
  )
)
from totals
cross join pipeline
cross join content;
$$;

create or replace function public.teacher_subject_metrics(
  p_tenant uuid,
  p_teacher uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select p.id
  from public.profiles p
  where p.id = p_teacher
    and p.tenant_id = p_tenant
    and p.role = 'teacher'
), assigned as (
  select subject.id, subject.name, subject.course_id, subject.course_level_id,
    course.name as course_name,
    level.name as level_name
  from public.teacher_subjects assignment
  join actor on true
  join public.subjects subject
    on subject.id = assignment.subject_id
   and subject.tenant_id = p_tenant
  join public.courses course
    on course.id = subject.course_id
   and course.tenant_id = p_tenant
  left join public.course_levels level
    on level.id = subject.course_level_id
   and level.tenant_id = p_tenant
   and level.course_id = subject.course_id
  where assignment.tenant_id = p_tenant
    and assignment.teacher_id = p_teacher
), chapter_counts as (
  select chapter.subject_id, count(*)::int as chapters
  from public.chapters chapter
  join assigned on assigned.id = chapter.subject_id
  where chapter.tenant_id = p_tenant
  group by chapter.subject_id
), question_counts as (
  select chapter.subject_id,
    count(*)::int as questions,
    count(*) filter (where question.review_status = 'pending_review')::int as pending_review,
    count(*) filter (where question.review_status = 'needs_edit')::int as needs_edit
  from public.questions question
  join public.chapters chapter
    on chapter.id = question.chapter_id
   and chapter.tenant_id = p_tenant
  join assigned on assigned.id = chapter.subject_id
  where question.tenant_id = p_tenant
    and question.created_by = p_teacher
  group by chapter.subject_id
), quiz_counts as (
  select quiz.subject_id,
    count(*)::int as quizzes_total,
    count(*) filter (where quiz.status = 'published')::int as quizzes_published,
    count(*) filter (where quiz.status = 'draft')::int as quizzes_draft
  from public.quiz_sets quiz
  join assigned on assigned.id = quiz.subject_id
  where quiz.tenant_id = p_tenant
    and quiz.created_by = p_teacher
  group by quiz.subject_id
), teacher_variants as (
  select quiz.subject_id, variant.id, variant.total_marks
  from public.quiz_sets quiz
  join assigned on assigned.id = quiz.subject_id
  join public.quiz_variants variant
    on variant.quiz_set_id = quiz.id
   and variant.tenant_id = p_tenant
  where quiz.tenant_id = p_tenant
    and quiz.created_by = p_teacher
), attempt_counts as (
  select variant.subject_id,
    count(*)::int as attempts,
    count(distinct attempt.student_id)::int as students,
    coalesce(sum(
      least(greatest(attempt.total_score, 0), variant.total_marks)
    ) filter (where variant.total_marks > 0 and attempt.total_score is not null), 0)::numeric as score_earned,
    coalesce(sum(variant.total_marks)
      filter (where variant.total_marks > 0 and attempt.total_score is not null), 0)::numeric as score_possible
  from teacher_variants variant
  join public.quiz_attempts attempt
    on attempt.variant_id = variant.id
   and attempt.tenant_id = p_tenant
   and attempt.status = 'graded'
  group by variant.subject_id
)
select coalesce(jsonb_agg(jsonb_build_object(
  'id', subject.id,
  'name', subject.name,
  'course_name', subject.course_name,
  'level_name', coalesce(subject.level_name, ''),
  'chapters', coalesce(chapters.chapters, 0),
  'quizzes_total', coalesce(quizzes.quizzes_total, 0),
  'quizzes_published', coalesce(quizzes.quizzes_published, 0),
  'quizzes_draft', coalesce(quizzes.quizzes_draft, 0),
  'questions', coalesce(questions.questions, 0),
  'pending_review', coalesce(questions.pending_review, 0),
  'needs_edit', coalesce(questions.needs_edit, 0),
  'attempts', coalesce(attempts.attempts, 0),
  'students', coalesce(attempts.students, 0),
  'avg_score_pct', case when coalesce(attempts.score_possible, 0) > 0
    then round(attempts.score_earned / attempts.score_possible * 100, 1)
    else null end,
  'score_earned', coalesce(attempts.score_earned, 0),
  'score_possible', coalesce(attempts.score_possible, 0)
) order by lower(subject.name), subject.id), '[]'::jsonb)
from assigned subject
left join chapter_counts chapters on chapters.subject_id = subject.id
left join question_counts questions on questions.subject_id = subject.id
left join quiz_counts quizzes on quizzes.subject_id = subject.id
left join attempt_counts attempts on attempts.subject_id = subject.id;
$$;

create or replace function public.teacher_chapter_metrics(
  p_tenant uuid,
  p_teacher uuid,
  p_subject uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with allowed_subject as (
  select subject.id
  from public.profiles actor
  join public.teacher_subjects assignment
    on assignment.teacher_id = actor.id
   and assignment.tenant_id = actor.tenant_id
  join public.subjects subject
    on subject.id = assignment.subject_id
   and subject.tenant_id = assignment.tenant_id
  where actor.id = p_teacher
    and actor.tenant_id = p_tenant
    and actor.role = 'teacher'
    and assignment.subject_id = p_subject
), quiz_counts as (
  select quiz.chapter_id, count(*)::int as amount
  from public.quiz_sets quiz
  join allowed_subject on true
  where quiz.tenant_id = p_tenant
    and quiz.subject_id = p_subject
    and quiz.chapter_id is not null
  group by quiz.chapter_id
), question_counts as (
  select question.chapter_id, count(*)::int as amount
  from public.questions question
  join public.chapters chapter
    on chapter.id = question.chapter_id
   and chapter.tenant_id = p_tenant
   and chapter.subject_id = p_subject
  join allowed_subject on true
  where question.tenant_id = p_tenant
    and question.chapter_id is not null
  group by question.chapter_id
)
select coalesce(jsonb_agg(jsonb_build_object(
  'id', chapter.id,
  'name', chapter.name,
  'order_index', chapter.order_index,
  'quiz_count', coalesce(quizzes.amount, 0),
  'question_count', coalesce(questions.amount, 0)
) order by chapter.order_index, chapter.name, chapter.id), '[]'::jsonb)
from public.chapters chapter
join allowed_subject on allowed_subject.id = chapter.subject_id
left join quiz_counts quizzes on quizzes.chapter_id = chapter.id
left join question_counts questions on questions.chapter_id = chapter.id
where chapter.tenant_id = p_tenant;
$$;

create or replace function public.teacher_published_quiz_metrics(
  p_tenant uuid,
  p_teacher uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with actor as (
  select p.id
  from public.profiles p
  where p.id = p_teacher
    and p.tenant_id = p_tenant
    and p.role = 'teacher'
), assigned_subjects as (
  select subject.id, subject.name, subject.course_id
  from public.teacher_subjects assignment
  join actor on true
  join public.subjects subject
    on subject.id = assignment.subject_id
   and subject.tenant_id = p_tenant
  where assignment.tenant_id = p_tenant
    and assignment.teacher_id = p_teacher
), published_sets as (
  select quiz.id, quiz.title, quiz.subject_id, quiz.published_at,
    subject.name as subject_name, subject.course_id
  from public.quiz_sets quiz
  join assigned_subjects subject on subject.id = quiz.subject_id
  where quiz.tenant_id = p_tenant
    and quiz.created_by = p_teacher
    and quiz.status = 'published'
), eligible as (
  select subject.course_id, count(distinct enrollment.profile_id)::int as students
  from (select distinct course_id from assigned_subjects) subject
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
    'subject', quiz.subject_name,
    'published_at', quiz.published_at,
    'eligible_students', coalesce(eligible.students, 0),
    'completed_students', coalesce(attempts.completed_students, 0),
    'not_started_students', greatest(
      coalesce(eligible.students, 0) - coalesce(attempts.completed_students, 0),
      0
    ),
    'total_attempts', coalesce(attempts.total_attempts, 0),
    'average_accuracy', coalesce(attempts.average_accuracy, 0),
    'highest_accuracy', coalesce(attempts.highest_accuracy, 0),
    'lowest_accuracy', coalesce(attempts.lowest_accuracy, 0),
    'last_activity', attempts.last_activity
  ) order by quiz.published_at desc nulls last, quiz.id), '[]'::jsonb)
)
from published_sets quiz
left join eligible on eligible.course_id = quiz.course_id
left join attempt_counts attempts on attempts.quiz_set_id = quiz.id;
$$;

revoke all on function public.teacher_class_overview_metrics(uuid, uuid)
  from public, anon, authenticated;
revoke all on function public.teacher_subject_metrics(uuid, uuid)
  from public, anon, authenticated;
revoke all on function public.teacher_chapter_metrics(uuid, uuid, uuid)
  from public, anon, authenticated;
revoke all on function public.teacher_published_quiz_metrics(uuid, uuid)
  from public, anon, authenticated;

grant execute on function public.teacher_class_overview_metrics(uuid, uuid)
  to service_role;
grant execute on function public.teacher_subject_metrics(uuid, uuid)
  to service_role;
grant execute on function public.teacher_chapter_metrics(uuid, uuid, uuid)
  to service_role;
grant execute on function public.teacher_published_quiz_metrics(uuid, uuid)
  to service_role;

commit;
notify pgrst, 'reload schema';
