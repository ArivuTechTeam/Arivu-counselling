-- Migration 56 - Paper profiles (Phase 6.3-D, commerce vertical pack)
-- Apply after migration 55. Additive + nullable + flag-gated: a course level with
-- no paper profile (every existing course level) generates exactly as today, and the
-- profile is only read into the generation prompt when COMMERCE_PACK_ENABLED is
-- on. It is the single place commerce context lives (exam body / level / paper /
-- assessment year / accounting framework), consulted by generation (B) and the
-- P6.2 exam standards. Backend writes via the service-role key; RLS mirrors
-- scoring_policies (read within tenant, staff manage).
begin;

create table if not exists public.paper_profiles (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  course_id       uuid not null,
  course_level_id uuid not null,
  exam_body       text,   -- e.g. ICAI, ICMAI, ICSI, ACCA, IMA
  level           text,   -- e.g. Foundation, Intermediate, Final
  paper           text,   -- e.g. Paper 4 - Business Economics
  assessment_year text,   -- e.g. 2025-26 (the applicable exam period)
  framework       text,   -- e.g. Indian GAAP, Ind AS, IFRS, US GAAP
  created_by      uuid,
  created_at      timestamptz not null default now(),
  constraint paper_profiles_course_tenant_fk
    foreign key (course_id, tenant_id)
    references public.courses(id, tenant_id) on delete cascade,
  constraint paper_profiles_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references public.course_levels(id, tenant_id, course_id) on delete cascade,
  constraint paper_profiles_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  unique (tenant_id, course_level_id)
);
create index if not exists idx_paper_profiles_tenant on public.paper_profiles(tenant_id);
create index if not exists idx_paper_profiles_course on public.paper_profiles(course_id);
create index if not exists idx_paper_profiles_level on public.paper_profiles(course_level_id);

alter table public.paper_profiles enable row level security;
revoke all on public.paper_profiles from public, anon, authenticated;
grant select, insert, update, delete on public.paper_profiles to service_role;
drop policy if exists "read own tenant paper profiles" on public.paper_profiles;
create policy "read own tenant paper profiles" on public.paper_profiles
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "institution admins manage paper profiles" on public.paper_profiles;
create policy "institution admins manage paper profiles" on public.paper_profiles
  for all using (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and p.tenant_id = paper_profiles.tenant_id
        and p.role = 'institution_admin'
    )
  ) with check (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and p.tenant_id = paper_profiles.tenant_id
        and p.role = 'institution_admin'
    )
  );

commit;
notify pgrst, 'reload schema';
