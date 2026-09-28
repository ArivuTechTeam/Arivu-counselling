-- Release A2 staging query-plan capture. Read-only, but EXPLAIN ANALYZE really
-- executes each aggregate function. Set all three UUIDs for a fake staging
-- teacher/current subject before running this file.
--
-- set arivupro.explain_tenant = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_teacher = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_subject = '00000000-0000-0000-0000-000000000000';

begin transaction read only;

do $$
begin
  if nullif(current_setting('arivupro.explain_tenant', true), '') is null
     or nullif(current_setting('arivupro.explain_teacher', true), '') is null
     or nullif(current_setting('arivupro.explain_subject', true), '') is null then
    raise exception 'Set arivupro.explain_tenant, explain_teacher, and explain_subject to fake staging UUIDs';
  end if;
end
$$;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and indexname in (
    'idx_teacher_subjects_tenant_teacher_subject',
    'idx_chapters_tenant_subject',
    'idx_documents_tenant_uploader_created',
    'idx_questions_tenant_creator_chapter',
    'idx_quizsets_tenant_creator_status',
    'idx_variants_tenant_quizset',
    'idx_vq_tenant_variant',
    'idx_attempts_tenant_variant_status',
    'idx_enrollments_tenant_course_profile'
  )
order by indexname;

explain (analyze, buffers, verbose, format text)
select public.teacher_class_overview_metrics(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_teacher')::uuid
);

explain (analyze, buffers, verbose, format text)
select public.teacher_subject_metrics(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_teacher')::uuid
);

explain (analyze, buffers, verbose, format text)
select public.teacher_chapter_metrics(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_teacher')::uuid,
  current_setting('arivupro.explain_subject')::uuid
);

explain (analyze, buffers, verbose, format text)
select public.teacher_published_quiz_metrics(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_teacher')::uuid
);

rollback;
