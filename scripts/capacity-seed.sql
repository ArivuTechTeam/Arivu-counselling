-- Release A1 synthetic content seed for an ISOLATED staging database only.
--
-- Safe by default: this script aborts unless the operator explicitly confirms
-- staging in the same transaction. It creates deterministic, fake content and
-- is idempotent for a given seed label. It does not create Auth users, attempts,
-- answers, documents, prompts, or personal information.
--
-- Smoke profile (default):
--   set arivupro.capacity_seed_confirmed = 'STAGING_ONLY';
--   \i scripts/capacity-seed.sql
--
-- Release A content profile (large: 750k published + 3.75m archived quiz sets,
-- 45m questions at 10 questions/quiz; size the staging project first):
--   set arivupro.capacity_seed_confirmed = 'STAGING_ONLY';
--   set arivupro.capacity_tenants = '10';
--   set arivupro.capacity_courses_per_tenant = '5';
--   set arivupro.capacity_levels_per_course = '3';
--   set arivupro.capacity_subjects_per_level = '5';
--   set arivupro.capacity_chapters_per_subject = '20';
--   set arivupro.capacity_published_quizzes_per_chapter = '50';
--   set arivupro.capacity_archived_quizzes_per_chapter = '250';
--   set arivupro.capacity_questions_per_quiz = '10';
--   \i scripts/capacity-seed.sql
--
-- Do not add this file to the migration chain. Run it only in disposable or
-- isolated staging after taking a backup and checking available storage.

begin;

do $$
begin
  if current_setting('arivupro.capacity_seed_confirmed', true) is distinct from 'STAGING_ONLY' then
    raise exception 'Capacity seed refused: set arivupro.capacity_seed_confirmed to STAGING_ONLY in this transaction';
  end if;
end
$$;

create temporary table capacity_seed_config on commit drop as
select
  coalesce(nullif(current_setting('arivupro.capacity_seed_label', true), ''), 'release-a1') as seed_label,
  coalesce(nullif(current_setting('arivupro.capacity_tenants', true), '')::integer, 2) as tenant_count,
  coalesce(nullif(current_setting('arivupro.capacity_courses_per_tenant', true), '')::integer, 1) as courses_per_tenant,
  coalesce(nullif(current_setting('arivupro.capacity_levels_per_course', true), '')::integer, 1) as levels_per_course,
  coalesce(nullif(current_setting('arivupro.capacity_subjects_per_level', true), '')::integer, 2) as subjects_per_level,
  coalesce(nullif(current_setting('arivupro.capacity_chapters_per_subject', true), '')::integer, 2) as chapters_per_subject,
  coalesce(nullif(current_setting('arivupro.capacity_published_quizzes_per_chapter', true), '')::integer, 2) as published_per_chapter,
  coalesce(nullif(current_setting('arivupro.capacity_archived_quizzes_per_chapter', true), '')::integer, 3) as archived_per_chapter,
  coalesce(nullif(current_setting('arivupro.capacity_questions_per_quiz', true), '')::integer, 5) as questions_per_quiz;

do $$
declare
  config capacity_seed_config%rowtype;
  estimated_questions bigint;
begin
  select * into config from capacity_seed_config;
  if config.tenant_count not between 1 and 10
     or config.courses_per_tenant not between 1 and 5
     or config.levels_per_course not between 1 and 3
     or config.subjects_per_level not between 1 and 5
     or config.chapters_per_subject not between 1 and 20
     or config.published_per_chapter not between 0 and 50
     or config.archived_per_chapter not between 0 and 250
     or config.questions_per_quiz not between 1 and 20 then
    raise exception 'Capacity seed dimensions exceed the reviewed Release A envelope';
  end if;
  estimated_questions := config.tenant_count::bigint
    * config.courses_per_tenant * config.levels_per_course
    * config.subjects_per_level * config.chapters_per_subject
    * (config.published_per_chapter + config.archived_per_chapter)
    * config.questions_per_quiz;
  raise notice 'Capacity seed % will create up to % synthetic questions', config.seed_label, estimated_questions;
end
$$;

insert into public.tenants (id, name, subdomain, plan_tier, is_active)
select
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no)::uuid,
  '[CAPACITY ' || config.seed_label || '] Institute ' || tenant_no,
  'capacity-' || left(md5(config.seed_label), 8) || '-' || tenant_no,
  'free',
  true
from capacity_seed_config config
cross join lateral generate_series(1, config.tenant_count) tenant_no
on conflict (id) do nothing;

insert into public.courses (id, tenant_id, name)
select
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no)::uuid,
  '[CAPACITY] Course ' || course_no
from capacity_seed_config config
cross join lateral generate_series(1, config.tenant_count) tenant_no
cross join lateral generate_series(1, config.courses_per_tenant) course_no
on conflict (id) do nothing;

insert into public.course_levels (id, tenant_id, course_id, name, is_active)
select
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no)::uuid,
  '[CAPACITY] Level ' || level_no,
  true
from capacity_seed_config config
cross join lateral generate_series(1, config.tenant_count) tenant_no
cross join lateral generate_series(1, config.courses_per_tenant) course_no
cross join lateral generate_series(1, config.levels_per_course) level_no
on conflict (id) do nothing;

insert into public.subjects (id, tenant_id, course_id, course_level_id, name)
select
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no)::uuid,
  '[CAPACITY] Level ' || level_no || ' Subject ' || subject_no
from capacity_seed_config config
cross join lateral generate_series(1, config.tenant_count) tenant_no
cross join lateral generate_series(1, config.courses_per_tenant) course_no
cross join lateral generate_series(1, config.levels_per_course) level_no
cross join lateral generate_series(1, config.subjects_per_level) subject_no
on conflict (id) do nothing;

insert into public.chapters (id, tenant_id, subject_id, name, order_index)
select
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || config.seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no)::uuid,
  '[CAPACITY] Chapter ' || chapter_no,
  chapter_no
from capacity_seed_config config
cross join lateral generate_series(1, config.tenant_count) tenant_no
cross join lateral generate_series(1, config.courses_per_tenant) course_no
cross join lateral generate_series(1, config.levels_per_course) level_no
cross join lateral generate_series(1, config.subjects_per_level) subject_no
cross join lateral generate_series(1, config.chapters_per_subject) chapter_no
on conflict (id) do nothing;

with dimensions as (
  select config.*, tenant_no, course_no, level_no, subject_no, chapter_no, quiz_no
  from capacity_seed_config config
  cross join lateral generate_series(1, config.tenant_count) tenant_no
  cross join lateral generate_series(1, config.courses_per_tenant) course_no
  cross join lateral generate_series(1, config.levels_per_course) level_no
  cross join lateral generate_series(1, config.subjects_per_level) subject_no
  cross join lateral generate_series(1, config.chapters_per_subject) chapter_no
  cross join lateral generate_series(1, config.published_per_chapter + config.archived_per_chapter) quiz_no
)
insert into public.quiz_sets (id, tenant_id, chapter_id, subject_id, title, status, published_at)
select
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no)::uuid,
  '[CAPACITY] Quiz ' || quiz_no,
  (case when quiz_no <= published_per_chapter then 'published' else 'archived' end)::public.quiz_status,
  case when quiz_no <= published_per_chapter then now() else null end
from dimensions
on conflict (id) do nothing;

with quiz_dimensions as (
  select config.*, tenant_no, course_no, level_no, subject_no, chapter_no, quiz_no
  from capacity_seed_config config
  cross join lateral generate_series(1, config.tenant_count) tenant_no
  cross join lateral generate_series(1, config.courses_per_tenant) course_no
  cross join lateral generate_series(1, config.levels_per_course) level_no
  cross join lateral generate_series(1, config.subjects_per_level) subject_no
  cross join lateral generate_series(1, config.chapters_per_subject) chapter_no
  cross join lateral generate_series(1, config.published_per_chapter + config.archived_per_chapter) quiz_no
)
insert into public.quiz_variants (id, tenant_id, quiz_set_id, variant_type, time_limit_minutes, total_marks)
select
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no || ':variant:1')::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no)::uuid,
  'theory',
  20,
  questions_per_quiz
from quiz_dimensions
on conflict (id) do nothing;

with question_dimensions as (
  select config.*, tenant_no, course_no, level_no, subject_no, chapter_no, quiz_no, question_no
  from capacity_seed_config config
  cross join lateral generate_series(1, config.tenant_count) tenant_no
  cross join lateral generate_series(1, config.courses_per_tenant) course_no
  cross join lateral generate_series(1, config.levels_per_course) level_no
  cross join lateral generate_series(1, config.subjects_per_level) subject_no
  cross join lateral generate_series(1, config.chapters_per_subject) chapter_no
  cross join lateral generate_series(1, config.published_per_chapter + config.archived_per_chapter) quiz_no
  cross join lateral generate_series(1, config.questions_per_quiz) question_no
)
insert into public.questions (
  id, tenant_id, chapter_id, type, question_text, options, correct_answer,
  explanation, difficulty, marks, source, verification_status, review_status
)
select
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no || ':question:' || question_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no)::uuid,
  'mcq_single',
  '[CAPACITY] Synthetic question ' || question_no,
  '[{"id":"a","text":"Synthetic correct option"},{"id":"b","text":"Synthetic distractor"}]'::jsonb,
  '"a"'::jsonb,
  '[CAPACITY] Synthetic explanation.',
  'medium',
  1,
  'manual',
  'verified',
  'approved'
from question_dimensions
on conflict (id) do nothing;

with question_dimensions as (
  select config.*, tenant_no, course_no, level_no, subject_no, chapter_no, quiz_no, question_no
  from capacity_seed_config config
  cross join lateral generate_series(1, config.tenant_count) tenant_no
  cross join lateral generate_series(1, config.courses_per_tenant) course_no
  cross join lateral generate_series(1, config.levels_per_course) level_no
  cross join lateral generate_series(1, config.subjects_per_level) subject_no
  cross join lateral generate_series(1, config.chapters_per_subject) chapter_no
  cross join lateral generate_series(1, config.published_per_chapter + config.archived_per_chapter) quiz_no
  cross join lateral generate_series(1, config.questions_per_quiz) question_no
)
insert into public.quiz_variant_questions (id, tenant_id, variant_id, question_id, order_index)
select
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no || ':link:' || question_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no)::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no || ':variant:1')::uuid,
  md5('arivupro-capacity:' || seed_label || ':tenant:' || tenant_no || ':course:' || course_no || ':level:' || level_no || ':subject:' || subject_no || ':chapter:' || chapter_no || ':quiz:' || quiz_no || ':question:' || question_no)::uuid,
  question_no - 1
from question_dimensions
on conflict (id) do nothing;

analyze public.tenants;
analyze public.courses;
analyze public.course_levels;
analyze public.subjects;
analyze public.chapters;
analyze public.quiz_sets;
analyze public.quiz_variants;
analyze public.questions;
analyze public.quiz_variant_questions;

select
  config.seed_label,
  (select count(*) from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%') as tenants,
  (select count(*) from public.courses where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as courses,
  (select count(*) from public.course_levels where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as course_levels,
  (select count(*) from public.subjects where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as subjects,
  (select count(*) from public.chapters where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as chapters,
  (select count(*) from public.quiz_sets where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as quiz_sets,
  (select count(*) from public.questions where tenant_id in (
    select id from public.tenants where name like '[CAPACITY ' || config.seed_label || ']%'
  )) as questions
from capacity_seed_config config;

commit;

reset arivupro.capacity_seed_confirmed;
