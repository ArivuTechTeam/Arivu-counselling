-- Migration 65: atomic paper-bank synchronization and descriptive-grading quota.
-- Apply after migrations 63-64, before PAPER_BANK_ENABLED is enabled.
begin;

-- The same question may appear in multiple source quizzes. Keep a separate
-- provenance link so republishing one quiz cannot delete another quiz's copy.
create table if not exists public.paper_question_sources (
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  paper_question_id uuid not null references public.paper_questions(id) on delete cascade,
  source_quiz_set_id uuid not null,
  origin_question_id uuid not null,
  primary key (tenant_id, source_quiz_set_id, origin_question_id)
);
create index if not exists idx_paper_question_sources_bank
  on public.paper_question_sources (paper_question_id);
alter table public.paper_question_sources enable row level security;
revoke all on public.paper_question_sources from public, anon, authenticated;
grant select, insert, update, delete on public.paper_question_sources to service_role;

-- Preserve lineage for snapshots written by the old non-atomic publisher.
insert into public.paper_question_sources (
  tenant_id, paper_question_id, source_quiz_set_id, origin_question_id
)
select tenant_id, id, source_quiz_set_id, origin_question_id
from public.paper_questions
where source_quiz_set_id is not null and origin_question_id is not null
on conflict do nothing;

-- Dedup only within the same subject and chapter. The previous tenant-wide
-- index could hide a question from a second subject that uses identical text.
drop index if exists public.uq_paper_dedup;
create unique index uq_paper_dedup
  on public.paper_questions (
    tenant_id, paper_type, subject_id,
    coalesce(chapter_id, '00000000-0000-0000-0000-000000000000'::uuid),
    content_hash, coalesce(year, ''), coalesce(exam, '')
  );

-- One RPC call is one Postgres transaction. Any failed insert or validation
-- rolls back all link and bank changes; old snapshots remain intact.
create or replace function public.sync_paper_questions(
  p_tenant_id uuid,
  p_quiz_set_id uuid,
  p_actor_id uuid,
  p_rows jsonb
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_subject_id uuid;
  v_document_id uuid;
  v_item jsonb;
  v_origin_id uuid;
  v_chapter_id uuid;
  v_bank_id uuid;
  v_old_bank_ids uuid[];
  v_desired_ids uuid[] := '{}'::uuid[];
  v_count integer := 0;
begin
  if current_user <> 'service_role' then
    raise exception 'Paper bank sync is service-role only';
  end if;
  if p_rows is null or jsonb_typeof(p_rows) <> 'array'
      or jsonb_array_length(p_rows) > 2000 then
    raise exception 'Invalid paper-bank snapshot input';
  end if;
  if not exists (
    select 1 from public.profiles
    where id = p_actor_id and tenant_id = p_tenant_id and role = 'teacher'
  ) then
    raise exception 'Publisher is not an active tenant teacher';
  end if;

  select subject_id, document_id into v_subject_id, v_document_id
  from public.quiz_sets
  where id = p_quiz_set_id and tenant_id = p_tenant_id and status = 'published'
  for update;
  if not found or v_subject_id is null then
    raise exception 'Published quiz or subject not found';
  end if;

  select coalesce(array_agg(distinct paper_question_id), '{}'::uuid[])
  into v_old_bank_ids
  from public.paper_question_sources
  where tenant_id = p_tenant_id and source_quiz_set_id = p_quiz_set_id;

  for v_item in select value from jsonb_array_elements(p_rows)
  loop
    v_origin_id := (v_item->>'origin_question_id')::uuid;
    v_chapter_id := nullif(v_item->>'chapter_id', '')::uuid;
    if v_origin_id is null or v_origin_id = any(v_desired_ids)
        or nullif(v_item->>'content_hash', '') is null
        or nullif(v_item->>'question_text', '') is null
        or (v_item->>'paper_type') not in ('pyq', 'mtp', 'rtp') then
      raise exception 'Invalid or repeated paper-bank question';
    end if;
    if not exists (
      select 1
      from public.questions q
      join public.quiz_variant_questions link
        on link.question_id = q.id and link.tenant_id = p_tenant_id
      join public.quiz_variants variant
        on variant.id = link.variant_id and variant.tenant_id = p_tenant_id
      where q.id = v_origin_id and q.tenant_id = p_tenant_id
        and q.review_status = 'approved'
        and q.paper_type = v_item->>'paper_type'
        and variant.quiz_set_id = p_quiz_set_id
    ) then
      raise exception 'Paper-bank question is not approved in this quiz';
    end if;
    if v_chapter_id is not null and not exists (
      select 1 from public.chapters
      where id = v_chapter_id and tenant_id = p_tenant_id
        and subject_id = v_subject_id
    ) then
      raise exception 'Paper-bank chapter does not belong to the subject';
    end if;

    insert into public.paper_questions (
      tenant_id, paper_type, subject_id, chapter_id, exam, year, type,
      question_text, options, correct_answer, explanation, marks, model_answer,
      answer_summary, content_hash, origin_question_id, source_quiz_set_id,
      source_document_id, created_by
    ) values (
      p_tenant_id, v_item->>'paper_type', v_subject_id, v_chapter_id,
      nullif(v_item->>'exam', ''), nullif(v_item->>'year', ''),
      (v_item->>'type')::public.question_type,
      v_item->>'question_text', v_item->'options', v_item->'correct_answer',
      v_item->>'explanation', coalesce((v_item->>'marks')::numeric, 1),
      v_item->>'model_answer', v_item->>'answer_summary',
      v_item->>'content_hash', v_origin_id, p_quiz_set_id,
      v_document_id, p_actor_id
    )
    on conflict do nothing;

    select id into v_bank_id from public.paper_questions
    where tenant_id = p_tenant_id and paper_type = v_item->>'paper_type'
      and subject_id = v_subject_id
      and chapter_id is not distinct from v_chapter_id
      and content_hash = v_item->>'content_hash'
      and coalesce(year, '') = coalesce(v_item->>'year', '')
      and coalesce(exam, '') = coalesce(v_item->>'exam', '');
    if v_bank_id is null then
      raise exception 'Paper-bank question could not be saved';
    end if;

    insert into public.paper_question_sources (
      tenant_id, paper_question_id, source_quiz_set_id, origin_question_id
    ) values (p_tenant_id, v_bank_id, p_quiz_set_id, v_origin_id)
    on conflict (tenant_id, source_quiz_set_id, origin_question_id)
    do update set paper_question_id = excluded.paper_question_id;

    v_desired_ids := array_append(v_desired_ids, v_origin_id);
    v_count := v_count + 1;
  end loop;

  delete from public.paper_question_sources
  where tenant_id = p_tenant_id and source_quiz_set_id = p_quiz_set_id
    and not (origin_question_id = any(v_desired_ids));

  -- Remove only entries that no source quiz still contributes. A shared item
  -- remains available if another quiz still points at it.
  delete from public.paper_questions bank
  where bank.tenant_id = p_tenant_id and bank.id = any(v_old_bank_ids)
    and not exists (
      select 1 from public.paper_question_sources source
      where source.paper_question_id = bank.id
    );
  return v_count;
end;
$$;
revoke all on function public.sync_paper_questions(uuid, uuid, uuid, jsonb)
  from public, anon, authenticated;
grant execute on function public.sync_paper_questions(uuid, uuid, uuid, jsonb)
  to service_role;

-- Give paid descriptive grading its own rolling-hour quota key.
alter table public.ai_rate_limits
  drop constraint if exists ai_rate_limits_endpoint_check,
  add constraint ai_rate_limits_endpoint_check check (endpoint in (
    'quiz_generation', 'blueprint_generation', 'topic_extraction',
    'question_regenerate', 'question_explain', 'quiz_extraction',
    'challenge_join', 'descriptive_grading'
  ));

create or replace function public.consume_ai_rate_limit(
  p_tenant_id uuid, p_user_id uuid, p_endpoint text, p_limit integer
)
returns table (allowed boolean, retry_after_seconds integer, remaining integer)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  request_time timestamptz := clock_timestamp();
  consumed_count integer;
  active_window_start timestamptz;
begin
  if p_limit < 1 then
    raise exception 'Rate limit must be a positive integer';
  end if;
  if p_endpoint not in (
    'quiz_generation', 'blueprint_generation', 'topic_extraction',
    'question_regenerate', 'question_explain', 'quiz_extraction',
    'challenge_join', 'descriptive_grading'
  ) then
    raise exception 'Unknown rate-limit endpoint';
  end if;

  insert into public.ai_rate_limits as limits (
    tenant_id, user_id, endpoint, window_started_at, request_count, updated_at
  ) values (p_tenant_id, p_user_id, p_endpoint, request_time, 1, request_time)
  on conflict (tenant_id, user_id, endpoint) do update
  set window_started_at = case
        when limits.window_started_at <= request_time - interval '1 hour'
          then request_time else limits.window_started_at end,
      request_count = case
        when limits.window_started_at <= request_time - interval '1 hour'
          then 1 else limits.request_count + 1 end,
      updated_at = request_time
  where limits.window_started_at <= request_time - interval '1 hour'
     or limits.request_count < p_limit
  returning limits.request_count, limits.window_started_at
  into consumed_count, active_window_start;

  if found then
    return query select true, 0, greatest(p_limit - consumed_count, 0);
    return;
  end if;
  select limits.window_started_at into active_window_start
  from public.ai_rate_limits as limits
  where limits.tenant_id = p_tenant_id and limits.user_id = p_user_id
    and limits.endpoint = p_endpoint;
  return query select false,
    greatest(1, ceil(extract(epoch from (
      active_window_start + interval '1 hour' - request_time
    )))::integer), 0;
end;
$$;
revoke all on function public.consume_ai_rate_limit(uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.consume_ai_rate_limit(uuid, uuid, text, integer)
  to service_role;

commit;
notify pgrst, 'reload schema';
