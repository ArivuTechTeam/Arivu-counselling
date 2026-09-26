-- Migration 70 — indexed, fair practice-bank sampling for Release A4.
-- Apply after migration 69 and before deploying the matching selector code.
begin;

-- A stable, uniformly distributed seek key lets selection start at a random
-- point without sorting the whole eligible bank with ORDER BY random().
alter table public.questions
  add column if not exists sampling_key bigint;

-- Migration 51 blocks every ordinary update to released questions. This
-- backfill changes only internal sampling metadata. ALTER TABLE holds the table
-- lock for this transaction, so no concurrent application write can pass while
-- the named user trigger is disabled. Any failure rolls this state back.
alter table public.questions
  disable trigger guard_released_question;

update public.questions
set sampling_key = floor(random() * 9223372036854775807::double precision)::bigint
where sampling_key is null;

alter table public.questions
  enable trigger guard_released_question;

alter table public.questions
  alter column sampling_key set default
    floor(random() * 9223372036854775807::double precision)::bigint;
alter table public.questions
  alter column sampling_key set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'public.questions'::regclass
      and conname = 'questions_sampling_key_nonnegative'
  ) then
    alter table public.questions
      add constraint questions_sampling_key_nonnegative
      check (sampling_key >= 0);
  end if;
end $$;

-- Equality scope comes first and the random seek key comes last. Separate
-- typed and untyped paths keep both Smart Practice and exact exam mixes bounded.
create index if not exists idx_questions_practice_chapter_sample
  on public.questions(tenant_id, chapter_id, sampling_key, id)
  include (type, difficulty)
  where review_status = 'approved'::public.review_status;
create index if not exists idx_questions_practice_chapter_type_sample
  on public.questions(tenant_id, chapter_id, type, sampling_key, id)
  include (difficulty)
  where review_status = 'approved'::public.review_status;
create index if not exists idx_vq_tenant_question_variant
  on public.quiz_variant_questions(tenant_id, question_id, variant_id);

create or replace function public.select_practice_question_ids_page(
  p_tenant uuid,
  p_student uuid,
  p_limit integer,
  p_start_key bigint,
  p_batches_enabled boolean,
  p_subject uuid,
  p_chapter uuid,
  p_difficulty text,
  p_question_type text
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
), enrolled_subjects as materialized (
  select distinct subject.id
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
), forward as materialized (
  select question.id, question.sampling_key, 0 as seek_phase
  from public.questions question
  join public.chapters chapter
    on chapter.id = question.chapter_id
   and chapter.tenant_id = p_tenant
  join enrolled_subjects enrolled on enrolled.id = chapter.subject_id
  where question.tenant_id = p_tenant
    and question.review_status = 'approved'
    and question.sampling_key >= greatest(coalesce(p_start_key, 0), 0)
    and (p_subject is null or chapter.subject_id = p_subject)
    and (p_chapter is null or chapter.id = p_chapter)
    and (p_difficulty is null or question.difficulty = p_difficulty)
    and (
      p_question_type is null
      or question.type = p_question_type::public.question_type
    )
    and (
      not exists (
        select 1
        from public.quiz_variant_questions link
        where link.tenant_id = p_tenant
          and link.question_id = question.id
      )
      or exists (
        select 1
        from public.quiz_variant_questions link
        join public.quiz_variants variant
          on variant.id = link.variant_id
         and variant.tenant_id = p_tenant
        join public.quiz_sets quiz
          on quiz.id = variant.quiz_set_id
         and quiz.tenant_id = p_tenant
         and quiz.status = 'published'
        where link.tenant_id = p_tenant
          and link.question_id = question.id
          and (
            not p_batches_enabled
            or coalesce(quiz.audience_mode, 'legacy_course') = 'legacy_course'
            or (
              quiz.audience_mode = 'assigned_batches'
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
      )
    )
  order by question.sampling_key, question.id
  limit least(greatest(p_limit, 1), 100)
), wrapped as materialized (
  select question.id, question.sampling_key, 1 as seek_phase
  from public.questions question
  join public.chapters chapter
    on chapter.id = question.chapter_id
   and chapter.tenant_id = p_tenant
  join enrolled_subjects enrolled on enrolled.id = chapter.subject_id
  where question.tenant_id = p_tenant
    and question.review_status = 'approved'
    and question.sampling_key < greatest(coalesce(p_start_key, 0), 0)
    and (p_subject is null or chapter.subject_id = p_subject)
    and (p_chapter is null or chapter.id = p_chapter)
    and (p_difficulty is null or question.difficulty = p_difficulty)
    and (
      p_question_type is null
      or question.type = p_question_type::public.question_type
    )
    and (
      not exists (
        select 1
        from public.quiz_variant_questions link
        where link.tenant_id = p_tenant
          and link.question_id = question.id
      )
      or exists (
        select 1
        from public.quiz_variant_questions link
        join public.quiz_variants variant
          on variant.id = link.variant_id
         and variant.tenant_id = p_tenant
        join public.quiz_sets quiz
          on quiz.id = variant.quiz_set_id
         and quiz.tenant_id = p_tenant
         and quiz.status = 'published'
        where link.tenant_id = p_tenant
          and link.question_id = question.id
          and (
            not p_batches_enabled
            or coalesce(quiz.audience_mode, 'legacy_course') = 'legacy_course'
            or (
              quiz.audience_mode = 'assigned_batches'
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
      )
    )
  order by question.sampling_key, question.id
  limit greatest(
    least(greatest(p_limit, 1), 100) - (select count(*) from forward),
    0
  )
), picked as (
  select * from forward
  union all
  select * from wrapped
)
select jsonb_build_object(
  'question_ids', coalesce(
    jsonb_agg(id order by seek_phase, sampling_key, id),
    '[]'::jsonb
  ),
  'available', count(*)::integer
)
from picked;
$$;

revoke all on function public.select_practice_question_ids_page(
  uuid, uuid, integer, bigint, boolean, uuid, uuid, text, text
) from public, anon, authenticated;
grant execute on function public.select_practice_question_ids_page(
  uuid, uuid, integer, bigint, boolean, uuid, uuid, text, text
) to service_role;

commit;
notify pgrst, 'reload schema';
