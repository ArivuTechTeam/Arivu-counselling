-- Migration 48 — Batches, memberships & quiz assignments (Phase 6.1)
-- Apply after migrations 01–47. Additive and safe; no existing behaviour changes.
-- Gated by the backend flag BATCHES_ENABLED (default false): creating these
-- objects and defaulting quiz_sets.audience_mode='legacy_course' preserves the
-- current course-wide student access until the flag is turned on per rollout.
-- Backend writes go through the service_role key (bypasses RLS); the policies
-- below are read/defense-in-depth and mirror the existing hierarchy tables.
begin;

-- A batch (cohort) within a course, e.g. "CA Foundation 2026".
create table if not exists public.batches (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references public.tenants(id) on delete cascade,
  course_id    uuid not null references public.courses(id) on delete cascade,
  name         text not null,
  exam_session text,
  starts_on    date,
  ends_on      date,
  status       text not null default 'active' check (status in ('active','archived')),
  created_by   uuid references public.profiles(id),
  created_at   timestamptz not null default now(),
  unique (tenant_id, course_id, name)
);
create index if not exists idx_batches_tenant_course on public.batches(tenant_id, course_id);

-- Student/teacher membership of a batch. Students self-select at signup; staff
-- can view/correct. A student may belong to several batches.
create table if not exists public.batch_memberships (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  batch_id        uuid not null references public.batches(id) on delete cascade,
  profile_id      uuid not null references public.profiles(id) on delete cascade,
  membership_role text not null default 'student' check (membership_role in ('student','teacher')),
  active          boolean not null default true,
  valid_from      date,
  valid_to        date,
  created_at      timestamptz not null default now(),
  unique (tenant_id, batch_id, profile_id)
);
create index if not exists idx_batch_memberships_member on public.batch_memberships(tenant_id, profile_id, active);
create index if not exists idx_batch_memberships_batch  on public.batch_memberships(tenant_id, batch_id);

-- Assignment of a published quiz to a batch, with an OPTIONAL availability window.
create table if not exists public.quiz_assignments (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references public.tenants(id) on delete cascade,
  quiz_set_id    uuid not null references public.quiz_sets(id) on delete cascade,
  batch_id       uuid not null references public.batches(id) on delete cascade,
  available_from timestamptz,
  available_to   timestamptz,
  status         text not null default 'active' check (status in ('active','withdrawn')),
  created_by     uuid references public.profiles(id),
  created_at     timestamptz not null default now(),
  unique (tenant_id, quiz_set_id, batch_id)
);
create index if not exists idx_quiz_assignments_batch on public.quiz_assignments(tenant_id, batch_id, status);
create index if not exists idx_quiz_assignments_quiz  on public.quiz_assignments(tenant_id, quiz_set_id);

-- Audience mode: existing + non-commerce quizzes stay 'legacy_course' (course-wide,
-- unchanged). New commerce quizzes use 'assigned_batches' (visible only to an
-- assigned batch's active members within the window). The default backfills every
-- existing row, so this alter changes no current visibility.
alter table public.quiz_sets add column if not exists audience_mode text not null default 'legacy_course';
do $$ begin
  alter table public.quiz_sets add constraint quiz_sets_audience_mode_check
    check (audience_mode in ('legacy_course','assigned_batches'));
exception when duplicate_object then null; end $$;

-- ---------- RLS (mirrors academic-hierarchy / enrollment policies) ----------
alter table public.batches enable row level security;
drop policy if exists "read own tenant batches" on public.batches;
create policy "read own tenant batches" on public.batches
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage batches" on public.batches;
create policy "staff manage batches" on public.batches
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

alter table public.batch_memberships enable row level security;
drop policy if exists "read own membership or staff" on public.batch_memberships;
create policy "read own membership or staff" on public.batch_memberships
  for select using (tenant_id = current_tenant_id() and (profile_id = auth.uid() or is_staff()));
drop policy if exists "staff manage memberships" on public.batch_memberships;
create policy "staff manage memberships" on public.batch_memberships
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

alter table public.quiz_assignments enable row level security;
drop policy if exists "staff read assignments" on public.quiz_assignments;
create policy "staff read assignments" on public.quiz_assignments
  for select using (tenant_id = current_tenant_id() and is_staff());
drop policy if exists "staff manage assignments" on public.quiz_assignments;
create policy "staff manage assignments" on public.quiz_assignments
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

commit;
notify pgrst, 'reload schema';
