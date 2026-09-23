-- Migration 50 — Scoring policies (Phase 6.2, per-question scoring engine)
-- Apply after migration 49. Additive and behaviour-neutral: a quiz with no
-- scoring_policy_id (the default for every existing row) scores exactly as today
-- (full marks / zero), and SCORING_POLICIES_ENABLED (default false) gates whether
-- an attached policy is honoured at all. Backend writes via the service-role key.
begin;

-- A named, reusable scoring policy. `rules` is a bounded JSON contract validated
-- in the backend (wrong_penalty, penalty_is_fraction, omission_score, multi_mode,
-- clamp_negative_total, numeric contract). Immutable in spirit once attached; a
-- change should create a new policy so historical attempts keep their snapshot.
create table if not exists public.scoring_policies (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references public.tenants(id) on delete cascade,
  name       text not null,
  rules      jsonb not null default '{}'::jsonb,
  created_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create index if not exists idx_scoring_policies_tenant on public.scoring_policies(tenant_id);

-- Optional per-quiz scoring policy. NULL = default full/zero (unchanged).
alter table public.quiz_sets
  add column if not exists scoring_policy_id uuid references public.scoring_policies(id) on delete set null;

-- The resolved policy is frozen onto the attempt/session at start, so changing a
-- policy later never alters a past score (mirrors the question snapshot).
alter table public.quiz_attempts     add column if not exists scoring_policy_snapshot jsonb;
alter table public.practice_sessions add column if not exists scoring_policy_snapshot jsonb;

alter table public.scoring_policies enable row level security;
drop policy if exists "read own tenant scoring policies" on public.scoring_policies;
create policy "read own tenant scoring policies" on public.scoring_policies
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage scoring policies" on public.scoring_policies;
create policy "staff manage scoring policies" on public.scoring_policies
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

commit;
notify pgrst, 'reload schema';
