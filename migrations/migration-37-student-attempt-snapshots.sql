-- Freeze the exact question paper and scoring data when a student starts.
-- Existing attempts keep an empty snapshot and use the backend's legacy fallback.

alter table public.quiz_attempts
  add column if not exists question_snapshot jsonb not null default '[]'::jsonb;

alter table public.practice_sessions
  add column if not exists question_snapshot jsonb not null default '[]'::jsonb;

drop function if exists public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer
);

create or replace function public.create_limited_quiz_attempt(
  p_tenant_id uuid,
  p_variant_id uuid,
  p_student_id uuid,
  p_started_at timestamptz,
  p_max_attempts integer,
  p_question_snapshot jsonb
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  created_id uuid;
begin
  if p_max_attempts < 1 then
    raise exception 'quiz_attempt_limit_invalid' using errcode = '22023';
  end if;
  if jsonb_typeof(p_question_snapshot) <> 'array'
     or jsonb_array_length(p_question_snapshot) < 1 then
    raise exception 'quiz_attempt_snapshot_invalid' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      p_student_id::text || ':' || p_variant_id::text,
      0
    )
  );
  if (
    select count(*) >= p_max_attempts
    from public.quiz_attempts attempts
    where attempts.tenant_id = p_tenant_id
      and attempts.student_id = p_student_id
      and attempts.variant_id = p_variant_id
  ) then
    raise exception 'quiz_attempt_limit_reached' using errcode = '23514';
  end if;

  insert into public.quiz_attempts (
    tenant_id,
    variant_id,
    student_id,
    status,
    started_at,
    question_snapshot
  ) values (
    p_tenant_id,
    p_variant_id,
    p_student_id,
    'in_progress',
    p_started_at,
    p_question_snapshot
  ) returning id into created_id;

  return created_id;
end;
$$;

revoke all on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb
) from public, anon, authenticated;

grant execute on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb
) to service_role;

notify pgrst, 'reload schema';
