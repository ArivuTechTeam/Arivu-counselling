-- ============================================================================
-- Migration 45 — Global course catalogue and tenant provisioning
-- Apply after migration-44-challenge-join-codes.sql.
--
-- The existing courses/subjects tables remain tenant-scoped operational rows.
-- Catalogue links are nullable so all existing and future free-form rows remain
-- valid. provision_catalog_subject() is service-role only and performs one
-- atomic, idempotent catalogue-to-tenant provisioning operation.
-- ============================================================================

create table if not exists public.catalog_courses (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  is_active boolean not null default true,
  display_order integer not null default 0
);

create table if not exists public.catalog_course_levels (
  id uuid primary key default gen_random_uuid(),
  catalog_course_id uuid not null
    references public.catalog_courses(id) on delete cascade,
  name text not null,
  is_active boolean not null default true,
  display_order integer not null default 0,
  unique (catalog_course_id, name)
);
create index if not exists idx_catalog_course_levels_course
  on public.catalog_course_levels(catalog_course_id);

create table if not exists public.catalog_course_subjects (
  id uuid primary key default gen_random_uuid(),
  catalog_level_id uuid not null
    references public.catalog_course_levels(id) on delete cascade,
  name text not null,
  is_active boolean not null default true,
  unique (catalog_level_id, name)
);
create index if not exists idx_catalog_course_subjects_level
  on public.catalog_course_subjects(catalog_level_id);

alter table public.courses
  add column if not exists catalog_course_id uuid
    references public.catalog_courses(id) on delete set null;
alter table public.subjects
  add column if not exists catalog_subject_id uuid
    references public.catalog_course_subjects(id) on delete set null;

create index if not exists idx_courses_catalog_course
  on public.courses(catalog_course_id);
create index if not exists idx_subjects_catalog_subject
  on public.subjects(catalog_subject_id);

create table if not exists public.institution_offerings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  catalog_subject_id uuid not null
    references public.catalog_course_subjects(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (tenant_id, catalog_subject_id)
);
create index if not exists idx_institution_offerings_tenant
  on public.institution_offerings(tenant_id);
create index if not exists idx_institution_offerings_subject
  on public.institution_offerings(catalog_subject_id);

-- Migration 18's broad name indexes cannot represent a separate catalogue row
-- beside an identically named free-form row. Split the constraints by row type:
-- free-form rows keep their original uniqueness guarantee, while catalogue rows
-- are unique by stable catalogue identity and may coexist with name collisions.
drop index if exists public.uq_courses_tenant_name;
drop index if exists public.uq_subjects_tenant_course_name;

create unique index if not exists uq_courses_tenant_freeform_name
  on public.courses(tenant_id, name)
  where catalog_course_id is null;
create unique index if not exists uq_courses_tenant_catalog
  on public.courses(tenant_id, catalog_course_id)
  where catalog_course_id is not null;
create unique index if not exists uq_subjects_tenant_course_freeform_name
  on public.subjects(tenant_id, course_id, name)
  where catalog_subject_id is null;
create unique index if not exists uq_subjects_tenant_catalog
  on public.subjects(tenant_id, catalog_subject_id)
  where catalog_subject_id is not null;

alter table public.catalog_courses enable row level security;
alter table public.catalog_course_levels enable row level security;
alter table public.catalog_course_subjects enable row level security;
alter table public.institution_offerings enable row level security;

revoke all on table public.catalog_courses from public, anon, authenticated;
revoke all on table public.catalog_course_levels from public, anon, authenticated;
revoke all on table public.catalog_course_subjects from public, anon, authenticated;
revoke all on table public.institution_offerings from public, anon, authenticated;

grant select, insert, update, delete on table public.catalog_courses to authenticated;
grant select, insert, update, delete on table public.catalog_course_levels to authenticated;
grant select, insert, update, delete on table public.catalog_course_subjects to authenticated;
grant select, insert, update, delete on table public.catalog_courses to service_role;
grant select, insert, update, delete on table public.catalog_course_levels to service_role;
grant select, insert, update, delete on table public.catalog_course_subjects to service_role;
grant select, insert, delete on table public.institution_offerings to authenticated;
grant select, insert, update, delete on table public.institution_offerings to service_role;

drop policy if exists "authenticated read catalog courses" on public.catalog_courses;
create policy "authenticated read catalog courses" on public.catalog_courses
  for select to authenticated using (true);
drop policy if exists "authenticated read catalog levels" on public.catalog_course_levels;
create policy "authenticated read catalog levels" on public.catalog_course_levels
  for select to authenticated using (true);
drop policy if exists "authenticated read catalog subjects" on public.catalog_course_subjects;
create policy "authenticated read catalog subjects" on public.catalog_course_subjects
  for select to authenticated using (true);

-- Catalogue mutations are performed by trusted backend endpoints after a
-- super-admin role check. These policies also protect any future direct Data
-- API use; service_role bypasses RLS and remains server-side only.
drop policy if exists "super admins insert catalog courses" on public.catalog_courses;
create policy "super admins insert catalog courses" on public.catalog_courses
  for insert to authenticated with check ((select public.is_super_admin()));
drop policy if exists "super admins update catalog courses" on public.catalog_courses;
create policy "super admins update catalog courses" on public.catalog_courses
  for update to authenticated
  using ((select public.is_super_admin()))
  with check ((select public.is_super_admin()));
drop policy if exists "super admins delete catalog courses" on public.catalog_courses;
create policy "super admins delete catalog courses" on public.catalog_courses
  for delete to authenticated using ((select public.is_super_admin()));

drop policy if exists "super admins insert catalog levels" on public.catalog_course_levels;
create policy "super admins insert catalog levels" on public.catalog_course_levels
  for insert to authenticated with check ((select public.is_super_admin()));
drop policy if exists "super admins update catalog levels" on public.catalog_course_levels;
create policy "super admins update catalog levels" on public.catalog_course_levels
  for update to authenticated
  using ((select public.is_super_admin()))
  with check ((select public.is_super_admin()));
drop policy if exists "super admins delete catalog levels" on public.catalog_course_levels;
create policy "super admins delete catalog levels" on public.catalog_course_levels
  for delete to authenticated using ((select public.is_super_admin()));

drop policy if exists "super admins insert catalog subjects" on public.catalog_course_subjects;
create policy "super admins insert catalog subjects" on public.catalog_course_subjects
  for insert to authenticated with check ((select public.is_super_admin()));
drop policy if exists "super admins update catalog subjects" on public.catalog_course_subjects;
create policy "super admins update catalog subjects" on public.catalog_course_subjects
  for update to authenticated
  using ((select public.is_super_admin()))
  with check ((select public.is_super_admin()));
drop policy if exists "super admins delete catalog subjects" on public.catalog_course_subjects;
create policy "super admins delete catalog subjects" on public.catalog_course_subjects
  for delete to authenticated using ((select public.is_super_admin()));

drop policy if exists "tenant members read institution offerings" on public.institution_offerings;
create policy "tenant members read institution offerings" on public.institution_offerings
  for select to authenticated
  using (
    tenant_id = (select public.current_tenant_id())
    or (select public.is_super_admin())
  );
drop policy if exists "institution admins insert own offerings" on public.institution_offerings;
create policy "institution admins insert own offerings" on public.institution_offerings
  for insert to authenticated
  with check (
    (tenant_id = (select public.current_tenant_id())
      and (select public.current_role_name()) = 'institution_admin')
    or (select public.is_super_admin())
  );
drop policy if exists "institution admins delete own offerings" on public.institution_offerings;
create policy "institution admins delete own offerings" on public.institution_offerings
  for delete to authenticated
  using (
    (tenant_id = (select public.current_tenant_id())
      and (select public.current_role_name()) = 'institution_admin')
    or (select public.is_super_admin())
  );

create or replace function public.provision_catalog_subject(
  p_tenant_id uuid,
  p_catalog_subject_id uuid
)
returns table (
  course_id uuid,
  subject_id uuid,
  course_name_collision boolean,
  subject_name_collision boolean
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  catalog_course public.catalog_courses%rowtype;
  catalog_subject public.catalog_course_subjects%rowtype;
  resolved_course_id uuid;
  resolved_subject_id uuid;
  has_course_collision boolean;
  has_subject_collision boolean;
begin
  if not exists (select 1 from public.tenants where id = p_tenant_id) then
    raise exception 'Tenant not found';
  end if;

  select cc.*
  into catalog_course
  from public.catalog_course_subjects cs
  join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
  join public.catalog_courses cc on cc.id = cl.catalog_course_id
  where cs.id = p_catalog_subject_id
    and cs.is_active = true
    and cl.is_active = true
    and cc.is_active = true;

  if not found then
    raise exception 'Active catalog subject not found';
  end if;

  select cs.*
  into catalog_subject
  from public.catalog_course_subjects cs
  where cs.id = p_catalog_subject_id;

  select exists (
    select 1 from public.courses c
    where c.tenant_id = p_tenant_id
      and c.name = catalog_course.name
      and c.catalog_course_id is null
  ) into has_course_collision;

  insert into public.courses (tenant_id, name, catalog_course_id)
  values (p_tenant_id, catalog_course.name, catalog_course.id)
  on conflict (tenant_id, catalog_course_id)
    where catalog_course_id is not null
  do update set catalog_course_id = excluded.catalog_course_id
  returning id into resolved_course_id;

  select exists (
    select 1 from public.subjects s
    where s.tenant_id = p_tenant_id
      and s.course_id = resolved_course_id
      and s.name = catalog_subject.name
      and s.catalog_subject_id is null
  ) into has_subject_collision;

  insert into public.subjects (
    tenant_id,
    course_id,
    name,
    catalog_subject_id
  ) values (
    p_tenant_id,
    resolved_course_id,
    catalog_subject.name,
    catalog_subject.id
  )
  on conflict (tenant_id, catalog_subject_id)
    where catalog_subject_id is not null
  do update set catalog_subject_id = excluded.catalog_subject_id
  returning id into resolved_subject_id;

  insert into public.institution_offerings (tenant_id, catalog_subject_id)
  values (p_tenant_id, catalog_subject.id)
  on conflict (tenant_id, catalog_subject_id) do nothing;

  if has_course_collision or has_subject_collision then
    raise log 'Catalog provisioning kept same-name free-form rows separate (tenant %, catalog subject %, course collision %, subject collision %)',
      p_tenant_id, p_catalog_subject_id, has_course_collision, has_subject_collision;
  end if;

  return query select
    resolved_course_id,
    resolved_subject_id,
    has_course_collision,
    has_subject_collision;
end;
$$;

revoke all on function public.provision_catalog_subject(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.provision_catalog_subject(uuid, uuid)
  to service_role;

-- ============================================================================
-- END OF MIGRATION 45
-- ============================================================================
