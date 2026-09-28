-- Release A5 staging query-plan capture.
-- Run this read-only file immediately before migration 71 and save the output;
-- then run it again after migration 71 with the same staging IDs. Use only fake
-- production-shaped staging data, never real student answers.
--
-- set arivupro.explain_tenant = '00000000-0000-0000-0000-000000000000';
-- set arivupro.explain_question = '00000000-0000-0000-0000-000000000000';

begin transaction read only;

do $$
begin
  if nullif(current_setting('arivupro.explain_tenant', true), '') is null
     or nullif(current_setting('arivupro.explain_question', true), '') is null then
    raise exception 'Set arivupro.explain_tenant and explain_question to fake staging UUIDs';
  end if;
end
$$;

select tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in ('attempt_answers', 'practice_answers')
order by tablename, indexname;

explain (analyze, buffers, verbose, format text)
select answer.attempt_id
from public.attempt_answers answer
where answer.question_id = current_setting('arivupro.explain_question')::uuid
  and answer.tenant_id = current_setting('arivupro.explain_tenant')::uuid;

explain (analyze, buffers, verbose, format text)
select answer.session_id
from public.practice_answers answer
where answer.question_id = current_setting('arivupro.explain_question')::uuid
  and answer.tenant_id = current_setting('arivupro.explain_tenant')::uuid;

rollback;
