-- Migration 52 - Paper profiles (Phase 6.3-D, commerce vertical pack)
-- Apply after migration 51. Additive + nullable + flag-gated: a course with no
-- paper profile (every existing course) generates exactly as today, and the
-- profile is only read into the generation prompt when COMMERCE_PACK_ENABLED is
-- on. It is the single place commerce context lives (exam body / level / paper /
-- assessment year / accounting framework), consulted by generation (B) and the
-- P6.2 exam standards. Backend writes via the service-role key; RLS mirrors
-- scoring_policies (read within tenant, staff manage).
begin;

create table if not exists public.paper_profiles (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  course_id       uuid not null references public.courses(id) on delete cascade,
  exam_body       text,   -- e.g. ICAI, ICMAI, ICSI, ACCA, IMA
  level           text,   -- e.g. Foundation, Intermediate, Final
  paper           text,   -- e.g. Paper 4 - Business Economics
  assessment_year text,   -- e.g. 2025-26 (the applicable exam period)
  framework       text,   -- e.g. Indian GAAP, Ind AS, IFRS, US GAAP
  created_by      uuid references public.profiles(id),
  created_at      timestamptz not null default now(),
  unique (tenant_id, course_id)
);
create index if not exists idx_paper_profiles_tenant on public.paper_profiles(tenant_id);
create index if not exists idx_paper_profiles_course on public.paper_profiles(course_id);

alter table public.paper_profiles enable row level security;
drop policy if exists "read own tenant paper profiles" on public.paper_profiles;
create policy "read own tenant paper profiles" on public.paper_profiles
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage paper profiles" on public.paper_profiles;
create policy "staff manage paper profiles" on public.paper_profiles
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

commit;
notify pgrst, 'reload schema';
