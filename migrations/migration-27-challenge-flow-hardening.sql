-- Challenge-a-Friend hardening: immutable question snapshots, course scope,
-- expiry/revocation, atomic creator setup, and one session per participant.

alter table public.challenges
  add column if not exists subject_id uuid references public.subjects(id);

alter table public.challenges
  add column if not exists course_ids uuid[] not null default '{}'::uuid[];

alter table public.challenges
  add column if not exists question_snapshot jsonb not null default '[]'::jsonb;

alter table public.challenges
  add column if not exists duration_minutes integer;

alter table public.challenges
  add column if not exists expires_at timestamptz;

alter table public.challenges
  add column if not exists is_active boolean not null default true;

do $$
begin
  if exists (
    select 1
    from public.practice_sessions
    where challenge_id is not null
    group by challenge_id, student_id
    having count(*) > 1
  ) then
    raise exception using
      message = 'Duplicate challenge participants exist. Resolve them before applying migration 27.';
  end if;
end
$$;

create unique index if not exists uq_practice_challenge_participant
  on public.practice_sessions (challenge_id, student_id)
  where challenge_id is not null;

create index if not exists idx_challenges_creator_created
  on public.challenges (tenant_id, creator_id, created_at desc);

create index if not exists idx_challenges_active_expiry
  on public.challenges (tenant_id, expires_at)
  where is_active = true;

create or replace function public.create_challenge_with_session(
  p_tenant_id uuid,
  p_creator_id uuid,
  p_creator_name text,
  p_subject_id uuid,
  p_course_ids uuid[],
  p_question_ids jsonb,
  p_question_snapshot jsonb,
  p_duration_minutes integer,
  p_share_token text,
  p_expires_at timestamptz,
  p_started_at timestamptz
)
returns table(challenge_id uuid, session_id uuid, share_token text)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  created_challenge_id uuid;
  created_session_id uuid;
begin
  if p_duration_minutes < 1
     or jsonb_typeof(p_question_ids) <> 'array'
     or jsonb_array_length(p_question_ids) < 1
     or jsonb_typeof(p_question_snapshot) <> 'array'
     or jsonb_array_length(p_question_snapshot) <> jsonb_array_length(p_question_ids) then
    raise exception 'invalid_challenge_payload' using errcode = '22023';
  end if;

  insert into public.challenges (
    tenant_id,
    creator_id,
    creator_name,
    subject_id,
    course_ids,
    question_ids,
    question_snapshot,
    duration_minutes,
    share_token,
    expires_at,
    is_active
  ) values (
    p_tenant_id,
    p_creator_id,
    p_creator_name,
    p_subject_id,
    coalesce(p_course_ids, '{}'::uuid[]),
    p_question_ids,
    p_question_snapshot,
    p_duration_minutes,
    p_share_token,
    p_expires_at,
    true
  ) returning id into created_challenge_id;

  insert into public.practice_sessions (
    tenant_id,
    student_id,
    mode,
    subject_id,
    config,
    question_ids,
    status,
    challenge_id,
    started_at
  ) values (
    p_tenant_id,
    p_creator_id,
    'challenge',
    p_subject_id,
    jsonb_build_object(
      'count', jsonb_array_length(p_question_ids),
      'duration_minutes', p_duration_minutes
    ),
    p_question_ids,
    'in_progress',
    created_challenge_id,
    p_started_at
  ) returning id into created_session_id;

  return query select created_challenge_id, created_session_id, p_share_token;
end;
$$;

revoke all on function public.create_challenge_with_session(
  uuid, uuid, text, uuid, uuid[], jsonb, jsonb, integer, text, timestamptz,
  timestamptz
) from public, anon, authenticated;

grant execute on function public.create_challenge_with_session(
  uuid, uuid, text, uuid, uuid[], jsonb, jsonb, integer, text, timestamptz,
  timestamptz
) to service_role;

-- Snapshots contain answer keys. Only the trusted backend may read challenges.
revoke all on table public.challenges from anon, authenticated;
