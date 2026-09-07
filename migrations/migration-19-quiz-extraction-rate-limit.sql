-- Migration 19 — Include quiz extraction in the shared AI rate limiter.
-- Apply after migration-13-ai-rate-limits.sql and before deploying extraction.

alter table public.ai_rate_limits
  drop constraint if exists ai_rate_limits_endpoint_check,
  add constraint ai_rate_limits_endpoint_check check (endpoint in (
    'quiz_generation',
    'blueprint_generation',
    'topic_extraction',
    'question_regenerate',
    'question_explain',
    'quiz_extraction'
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
    'quiz_extraction'
  ) then
    raise exception 'Unknown AI rate-limit endpoint';
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
