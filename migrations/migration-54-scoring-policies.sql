-- Migration 54 — scoring policies and atomic attempt snapshots.
-- Apply after migration 53. Existing quizzes keep default full/zero scoring.
begin;

create table if not exists public.scoring_policies (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references public.tenants(id) on delete cascade,
  name       text not null,
  rules      jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint scoring_policies_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  unique (tenant_id, name),
  unique (id, tenant_id)
);
create index if not exists idx_scoring_policies_tenant
  on public.scoring_policies(tenant_id);

alter table public.quiz_sets add column if not exists scoring_policy_id uuid;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'quiz_sets_scoring_policy_tenant_fk'
      and conrelid = 'public.quiz_sets'::regclass
  ) then
    alter table public.quiz_sets
      add constraint quiz_sets_scoring_policy_tenant_fk
      foreign key (scoring_policy_id, tenant_id)
      references public.scoring_policies(id, tenant_id) on delete set null (scoring_policy_id);
  end if;
end $$;

alter table public.quiz_attempts
  add column if not exists scoring_policy_snapshot jsonb;
alter table public.practice_sessions
  add column if not exists scoring_policy_snapshot jsonb;

alter table public.scoring_policies enable row level security;
revoke all on public.scoring_policies from public, anon, authenticated;
grant select, insert, update, delete on public.scoring_policies to service_role;

drop policy if exists "read own tenant scoring policies" on public.scoring_policies;
create policy "read own tenant scoring policies" on public.scoring_policies
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "institution admins manage scoring policies" on public.scoring_policies;
create policy "institution admins manage scoring policies" on public.scoring_policies
  for all using (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.tenant_id = scoring_policies.tenant_id
        and p.role = 'institution_admin'
    )
  ) with check (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.tenant_id = scoring_policies.tenant_id
        and p.role = 'institution_admin'
    )
  );

-- Keep attempt-limit enforcement, the exact question paper, and the scoring
-- rules in one transaction. The six-argument version remains during rollout so
-- an older backend can coexist until the new deployment is healthy.
drop function if exists public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
);
create function public.create_limited_quiz_attempt(
  p_tenant_id uuid,
  p_variant_id uuid,
  p_student_id uuid,
  p_started_at timestamptz,
  p_max_attempts integer,
  p_question_snapshot jsonb,
  p_scoring_policy_snapshot jsonb
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
  if p_scoring_policy_snapshot is not null
     and jsonb_typeof(p_scoring_policy_snapshot) <> 'object' then
    raise exception 'scoring_policy_snapshot_invalid' using errcode = '22023';
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
    tenant_id, variant_id, student_id, status, started_at,
    question_snapshot, scoring_policy_snapshot
  ) values (
    p_tenant_id, p_variant_id, p_student_id, 'in_progress', p_started_at,
    p_question_snapshot, p_scoring_policy_snapshot
  ) returning id into created_id;
  return created_id;
end;
$$;

revoke all on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
) to service_role;

commit;
notify pgrst, 'reload schema';
