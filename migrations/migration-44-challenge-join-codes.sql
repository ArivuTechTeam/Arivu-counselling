-- Friendly, tenant-scoped Challenge a Friend join codes.
-- Apply after migrations 19 and 27, and before deploying code that reads
-- challenges.join_code or consumes the challenge_join rate-limit endpoint.
begin;

alter table public.challenges
  add column if not exists join_code text;

do $$
declare
  challenge_row record;
  alphabet constant text := '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
  random_bytes bytea;
  candidate text;
  byte_index integer;
begin
  for challenge_row in
    select id, tenant_id
    from public.challenges
    where join_code is null
    order by id
  loop
    loop
      random_bytes := gen_random_bytes(8);
      candidate := '';
      for byte_index in 0..7 loop
        candidate := candidate || substr(
          alphabet,
          (get_byte(random_bytes, byte_index) % length(alphabet)) + 1,
          1
        );
      end loop;
      exit when not exists (
        select 1
        from public.challenges existing
        where existing.tenant_id = challenge_row.tenant_id
          and existing.join_code = candidate
      );
    end loop;

    update public.challenges
    set join_code = candidate
    where id = challenge_row.id;
  end loop;
end
$$;

alter table public.challenges
  alter column join_code set not null;

alter table public.challenges
  drop constraint if exists challenges_join_code_format,
  add constraint challenges_join_code_format
    check (join_code ~ '^[2-9A-HJ-NP-Z]{8}$');

create unique index if not exists uq_challenges_tenant_join_code
  on public.challenges (tenant_id, join_code);

alter table public.ai_rate_limits
  drop constraint if exists ai_rate_limits_endpoint_check,
  add constraint ai_rate_limits_endpoint_check check (endpoint in (
    'quiz_generation',
    'blueprint_generation',
    'topic_extraction',
    'question_regenerate',
    'question_explain',
    'quiz_extraction',
    'challenge_join'
  ));

create or replace function public.consume_ai_rate_limit(
  p_tenant_id uuid,
  p_user_id uuid,
  p_endpoint text,
  p_limit integer
)
returns table (
  allowed boolean,
  retry_after_seconds integer,
  remaining integer
)
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
    'quiz_generation',
    'blueprint_generation',
    'topic_extraction',
    'question_regenerate',
    'question_explain',
    'quiz_extraction',
    'challenge_join'
  ) then
    raise exception 'Unknown rate-limit endpoint';
  end if;

  insert into public.ai_rate_limits as limits (
    tenant_id, user_id, endpoint, window_started_at, request_count, updated_at
  )
  values (p_tenant_id, p_user_id, p_endpoint, request_time, 1, request_time)
  on conflict (tenant_id, user_id, endpoint) do update
  set
    window_started_at = case
      when limits.window_started_at <= request_time - interval '1 hour'
        then request_time
      else limits.window_started_at
    end,
    request_count = case
      when limits.window_started_at <= request_time - interval '1 hour'
        then 1
      else limits.request_count + 1
    end,
    updated_at = request_time
  where
    limits.window_started_at <= request_time - interval '1 hour'
    or limits.request_count < p_limit
  returning limits.request_count, limits.window_started_at
  into consumed_count, active_window_start;

  if found then
    return query select true, 0, greatest(p_limit - consumed_count, 0);
    return;
  end if;

  select limits.window_started_at
  into active_window_start
  from public.ai_rate_limits as limits
  where limits.tenant_id = p_tenant_id
    and limits.user_id = p_user_id
    and limits.endpoint = p_endpoint;

  return query
  select
    false,
    greatest(
      1,
      ceil(extract(epoch from (
        active_window_start + interval '1 hour' - request_time
      )))::integer
    ),
    0;
end;
$$;

revoke all on function public.consume_ai_rate_limit(uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.consume_ai_rate_limit(uuid, uuid, text, integer)
  to service_role;

notify pgrst, 'reload schema';
commit;
