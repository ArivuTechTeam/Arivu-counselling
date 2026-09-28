-- Release A4 staging timing/index check. Use only fake staging identities and
-- run after migration 70. EXPLAIN ANALYZE executes the read-only selector.
--
-- set arivupro.explain_tenant = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_student = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_subject = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_chapter = '00000000-0000-0000-0000-000000000000';

begin transaction read only;

do $$
begin
  if nullif(current_setting('arivupro.explain_tenant', true), '') is null
     or nullif(current_setting('arivupro.explain_student', true), '') is null
     or nullif(current_setting('arivupro.explain_subject', true), '') is null
     or nullif(current_setting('arivupro.explain_chapter', true), '') is null then
    raise exception 'Set the A4 explain tenant, student, subject, and chapter to fake staging UUIDs';
  end if;
end
$$;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and indexname in (
    'idx_questions_practice_chapter_sample',
    'idx_questions_practice_chapter_type_sample',
    'idx_vq_tenant_question_variant',
    'idx_batch_memberships_member',
    'idx_quiz_assignments_quiz'
  )
order by indexname;

explain (analyze, buffers, verbose, format text)
select public.select_practice_question_ids_page(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_student')::uuid,
  100,
  4611686018427387904::bigint,
  true,
  current_setting('arivupro.explain_subject')::uuid,
  current_setting('arivupro.explain_chapter')::uuid,
  null,
  null
);

explain (analyze, buffers, verbose, format text)
select public.select_practice_question_ids_page(
  current_setting('arivupro.explain_tenant')::uuid,
  current_setting('arivupro.explain_student')::uuid,
  25,
  4611686018427387904::bigint,
  true,
  current_setting('arivupro.explain_subject')::uuid,
  null,
  'medium',
  'mcq_single'
);

rollback;
