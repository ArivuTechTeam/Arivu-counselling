-- Migration 52 — Level-aware batches, memberships and quiz assignments.
-- Apply after migrations 49-51 and the existing Course -> Level migration 47.
-- Browser roles remain denied; all application writes use the tenant-scoped API.
begin;

create unique index if not exists uq_courses_id_tenant
  on public.courses(id, tenant_id);
create unique index if not exists uq_quiz_sets_id_tenant
  on public.quiz_sets(id, tenant_id);

create table if not exists public.batches (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  course_id uuid not null,
  course_level_id uuid not null,
  name text not null,
  exam_session text,
  starts_on date,
  ends_on date,
  status text not null default 'active' check (status in ('active','archived')),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint batches_course_tenant_fk
    foreign key (course_id, tenant_id)
    references public.courses(id, tenant_id) on delete cascade,
  constraint batches_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references public.course_levels(id, tenant_id, course_id) on delete cascade,
  constraint batches_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  constraint batches_tenant_level_name_key
    unique (tenant_id, course_level_id, name),
  constraint batches_id_tenant_key unique (id, tenant_id),
  constraint batches_dates_check
    check (starts_on is null or ends_on is null or starts_on <= ends_on)
);
create index if not exists idx_batches_tenant_level
  on public.batches(tenant_id, course_id, course_level_id, status);

create table if not exists public.batch_memberships (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  batch_id uuid not null,
  profile_id uuid not null,
  membership_role text not null default 'student'
    check (membership_role in ('student','teacher')),
  active boolean not null default true,
  valid_from date,
  valid_to date,
  created_at timestamptz not null default now(),
  constraint batch_memberships_batch_tenant_fk
    foreign key (batch_id, tenant_id)
    references public.batches(id, tenant_id) on delete cascade,
  constraint batch_memberships_profile_tenant_fk
    foreign key (profile_id, tenant_id)
    references public.profiles(id, tenant_id) on delete cascade,
  constraint batch_memberships_tenant_batch_profile_key
    unique (tenant_id, batch_id, profile_id),
  constraint batch_memberships_dates_check
    check (valid_from is null or valid_to is null or valid_from <= valid_to)
);
create index if not exists idx_batch_memberships_member
  on public.batch_memberships(tenant_id, profile_id, active);
create index if not exists idx_batch_memberships_batch
  on public.batch_memberships(tenant_id, batch_id);

create table if not exists public.quiz_assignments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  quiz_set_id uuid not null,
  batch_id uuid not null,
  available_from timestamptz,
  available_to timestamptz,
  status text not null default 'active' check (status in ('active','withdrawn')),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint quiz_assignments_quiz_tenant_fk
    foreign key (quiz_set_id, tenant_id)
    references public.quiz_sets(id, tenant_id) on delete cascade,
  constraint quiz_assignments_batch_tenant_fk
    foreign key (batch_id, tenant_id)
    references public.batches(id, tenant_id) on delete cascade,
  constraint quiz_assignments_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  constraint quiz_assignments_tenant_quiz_batch_key
    unique (tenant_id, quiz_set_id, batch_id),
  constraint quiz_assignments_window_check
    check (available_from is null or available_to is null or available_from <= available_to)
);
create index if not exists idx_quiz_assignments_batch
  on public.quiz_assignments(tenant_id, batch_id, status);
create index if not exists idx_quiz_assignments_quiz
  on public.quiz_assignments(tenant_id, quiz_set_id);

alter table public.quiz_sets
  add column if not exists audience_mode text not null default 'legacy_course';
do $$ begin
  alter table public.quiz_sets add constraint quiz_sets_audience_mode_check
    check (audience_mode in ('legacy_course','assigned_batches'));
exception when duplicate_object then null; end $$;

alter table public.batches enable row level security;
alter table public.batch_memberships enable row level security;
alter table public.quiz_assignments enable row level security;

revoke all on table public.batches, public.batch_memberships,
  public.quiz_assignments from public, anon, authenticated;
grant select, insert, update, delete on table public.batches,
  public.batch_memberships, public.quiz_assignments to service_role;

drop policy if exists "read own tenant batches" on public.batches;
create policy "read own tenant batches" on public.batches
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) or (select public.is_super_admin()));
drop policy if exists "institution admins manage batches" on public.batches;
create policy "institution admins manage batches" on public.batches
  for all to authenticated
  using (tenant_id = (select public.current_tenant_id())
         and (select public.current_role_name()) = 'institution_admin')
  with check (tenant_id = (select public.current_tenant_id())
              and (select public.current_role_name()) = 'institution_admin');

drop policy if exists "read own membership or admin" on public.batch_memberships;
create policy "read own membership or admin" on public.batch_memberships
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) and
         (profile_id = (select auth.uid()) or
          (select public.current_role_name()) = 'institution_admin'));
drop policy if exists "institution admins manage memberships" on public.batch_memberships;
create policy "institution admins manage memberships" on public.batch_memberships
  for all to authenticated
  using (tenant_id = (select public.current_tenant_id())
         and (select public.current_role_name()) = 'institution_admin')
  with check (tenant_id = (select public.current_tenant_id())
              and (select public.current_role_name()) = 'institution_admin');

drop policy if exists "staff read assignments" on public.quiz_assignments;
create policy "staff read assignments" on public.quiz_assignments
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) and (select public.is_staff()));

commit;
notify pgrst, 'reload schema';
