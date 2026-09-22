-- Operational Course -> Level -> Subject hierarchy and level-aware student signup.
-- Existing teacher enrollments and legacy student enrollments may keep a NULL
-- course_level_id; every new public student signup must provide a valid level.

create table if not exists public.course_levels (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  name text not null,
  catalog_level_id uuid references public.catalog_course_levels(id) on delete set null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (id, tenant_id, course_id)
);

create index if not exists idx_course_levels_tenant_course
  on public.course_levels(tenant_id, course_id);
create unique index if not exists uq_course_levels_tenant_catalog
  on public.course_levels(tenant_id, catalog_level_id)
  where catalog_level_id is not null;
create unique index if not exists uq_course_levels_course_custom_name
  on public.course_levels(course_id, lower(name))
  where catalog_level_id is null;

alter table public.subjects
  add column if not exists course_level_id uuid;

-- Materialize levels for all existing catalogue-backed subjects.
insert into public.course_levels (tenant_id, course_id, name, catalog_level_id)
select distinct s.tenant_id, s.course_id, cl.name, cl.id
from public.subjects s
join public.catalog_course_subjects cs on cs.id = s.catalog_subject_id
join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
on conflict (tenant_id, catalog_level_id) where catalog_level_id is not null
do update set name = excluded.name, course_id = excluded.course_id;

update public.subjects s
set course_level_id = level.id
from public.catalog_course_subjects cs
join public.course_levels level on level.catalog_level_id = cs.catalog_level_id
where s.catalog_subject_id = cs.id
  and level.tenant_id = s.tenant_id
  and level.course_id = s.course_id
  and s.course_level_id is null;

-- Keep existing free-form subjects usable by grouping them under a real level.
insert into public.course_levels (tenant_id, course_id, name)
select distinct s.tenant_id, s.course_id, 'General'
from public.subjects s
where s.course_level_id is null
on conflict (course_id, lower(name)) where catalog_level_id is null do nothing;

update public.subjects s
set course_level_id = level.id
from public.course_levels level
where level.tenant_id = s.tenant_id
  and level.course_id = s.course_id
  and level.catalog_level_id is null
  and lower(level.name) = 'general'
  and s.course_level_id is null;

alter table public.subjects
  alter column course_level_id set not null;
alter table public.subjects
  drop constraint if exists subjects_course_level_scope_fk;
alter table public.subjects
  add constraint subjects_course_level_scope_fk
  foreign key (course_level_id, tenant_id, course_id)
  references public.course_levels(id, tenant_id, course_id) on delete cascade;
create index if not exists idx_subjects_tenant_course_level
  on public.subjects(tenant_id, course_id, course_level_id);

alter table public.enrollments
  add column if not exists course_level_id uuid;
alter table public.enrollments
  drop constraint if exists enrollments_course_level_scope_fk;
alter table public.enrollments
  add constraint enrollments_course_level_scope_fk
  foreign key (course_level_id, tenant_id, course_id)
  references public.course_levels(id, tenant_id, course_id) on delete restrict;
create index if not exists idx_enrollments_student_level
  on public.enrollments(tenant_id, profile_id, course_level_id);

-- Existing students in a course with exactly one level can be migrated without
-- guessing. Multi-level legacy rows remain NULL and retain transitional
-- course-wide compatibility until they are corrected.
with single_level as (
  select tenant_id, course_id, (array_agg(id order by id))[1] as course_level_id
  from public.course_levels
  group by tenant_id, course_id
  having count(*) = 1
)
update public.enrollments enrollment
set course_level_id = single_level.course_level_id
from single_level, public.profiles profile
where profile.id = enrollment.profile_id
  and profile.role = 'student'::public.user_role
  and single_level.tenant_id = enrollment.tenant_id
  and single_level.course_id = enrollment.course_id
  and enrollment.course_level_id is null;

alter table public.course_levels enable row level security;
revoke all on table public.course_levels from public, anon, authenticated;
grant select, insert, update, delete on table public.course_levels to service_role;

drop policy if exists "read own tenant course levels" on public.course_levels;
create policy "read own tenant course levels" on public.course_levels
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) or (select public.is_super_admin()));
drop policy if exists "institution admins manage course levels" on public.course_levels;
create policy "institution admins manage course levels" on public.course_levels
  for all to authenticated
  using (
    tenant_id = (select public.current_tenant_id())
    and (select public.current_role_name()) = 'institution_admin'
  )
  with check (
    tenant_id = (select public.current_tenant_id())
    and (select public.current_role_name()) = 'institution_admin'
  );

-- Public signup metadata is untrusted. Validate the selected course and level
-- together, derive the tenant, and always create a student profile.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  requested_level uuid;
  google_oauth_signup boolean;
begin
  if coalesce(new.raw_user_meta_data->>'_backend_provisioning_intent', 'false') = 'true'
     or coalesce(new.raw_app_meta_data->>'provisioned_by_backend', 'false') = 'true' then
    return new;
  end if;

  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;
  requested_level := nullif(new.raw_user_meta_data->>'course_level_id', '')::uuid;
  google_oauth_signup :=
    coalesce(new.raw_app_meta_data->>'provider', '') = 'google'
    or (coalesce(new.raw_app_meta_data->'providers', '[]'::jsonb) ? 'google');

  if requested_course is null or requested_level is null then
    if google_oauth_signup then return new; end if;
    raise exception 'A valid course and level are required for public signup';
  end if;

  select c.tenant_id into selected_tenant
  from public.courses c
  join public.course_levels l
    on l.course_id = c.id and l.tenant_id = c.tenant_id and l.is_active = true
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = requested_course and l.id = requested_level;
  if selected_tenant is null then
    raise exception 'A valid course and level are required for public signup';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (new.id, selected_tenant, 'student'::public.user_role,
          new.raw_user_meta_data->>'full_name');
  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, new.id, requested_course, requested_level)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;
  return new;
end;
$$;

alter function public.handle_new_user() owner to postgres;
revoke all on function public.handle_new_user() from public, anon, authenticated, service_role;
grant execute on function public.handle_new_user() to supabase_auth_admin;

drop function if exists public.complete_google_signup(uuid);
create or replace function public.complete_google_signup(
  p_course_id uuid,
  p_course_level_id uuid
)
returns table (
  out_tenant_id uuid,
  out_role public.user_role,
  out_course_id uuid,
  out_course_level_id uuid
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
  user_metadata jsonb;
  app_metadata jsonb;
  selected_tenant uuid;
  existing_tenant uuid;
  existing_role public.user_role;
begin
  if current_user_id is null then raise exception 'Authentication is required'; end if;
  select u.raw_user_meta_data, u.raw_app_meta_data into user_metadata, app_metadata
  from auth.users u where u.id = current_user_id for update;
  if not found then raise exception 'Authenticated user not found'; end if;
  if coalesce(app_metadata->>'provider', '') <> 'google'
     and not (coalesce(app_metadata->'providers', '[]'::jsonb) ? 'google') then
    raise exception 'Google authentication is required';
  end if;

  select p.tenant_id, p.role into existing_tenant, existing_role
  from public.profiles p where p.id = current_user_id;
  if found then
    return query select existing_tenant, existing_role, null::uuid, null::uuid;
    return;
  end if;

  select c.tenant_id into selected_tenant
  from public.courses c
  join public.course_levels l
    on l.course_id = c.id and l.tenant_id = c.tenant_id and l.is_active = true
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = p_course_id and l.id = p_course_level_id;
  if selected_tenant is null then
    raise exception 'A valid course and level are required for Google signup';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (current_user_id, selected_tenant, 'student'::public.user_role,
          nullif(trim(coalesce(user_metadata->>'full_name', user_metadata->>'name')), ''));
  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, current_user_id, p_course_id, p_course_level_id)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;
  return query select selected_tenant, 'student'::public.user_role,
    p_course_id, p_course_level_id;
end;
$$;

revoke all on function public.complete_google_signup(uuid, uuid) from public, anon;
grant execute on function public.complete_google_signup(uuid, uuid) to authenticated;

-- Catalogue provisioning now materializes the operational level before subject.
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
  catalog_level public.catalog_course_levels%rowtype;
  catalog_subject public.catalog_course_subjects%rowtype;
  resolved_course_id uuid;
  resolved_level_id uuid;
  resolved_subject_id uuid;
  has_course_collision boolean;
  has_subject_collision boolean;
begin
  if not exists (select 1 from public.tenants where id = p_tenant_id) then
    raise exception 'Tenant not found';
  end if;
  select cc.* into catalog_course
  from public.catalog_course_subjects cs
  join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
  join public.catalog_courses cc on cc.id = cl.catalog_course_id
  where cs.id = p_catalog_subject_id
    and cs.is_active = true and cl.is_active = true and cc.is_active = true;
  if not found then raise exception 'Active catalog subject not found'; end if;

  select cl.* into catalog_level
  from public.catalog_course_subjects cs
  join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
  where cs.id = p_catalog_subject_id;
  select cs.* into catalog_subject
  from public.catalog_course_subjects cs
  where cs.id = p_catalog_subject_id;

  select exists (
    select 1 from public.courses c where c.tenant_id = p_tenant_id
      and c.name = catalog_course.name and c.catalog_course_id is null
  ) into has_course_collision;
  insert into public.courses (tenant_id, name, catalog_course_id)
  values (p_tenant_id, catalog_course.name, catalog_course.id)
  on conflict (tenant_id, catalog_course_id) where catalog_course_id is not null
  do update set catalog_course_id = excluded.catalog_course_id
  returning id into resolved_course_id;

  insert into public.course_levels (tenant_id, course_id, name, catalog_level_id)
  values (p_tenant_id, resolved_course_id, catalog_level.name, catalog_level.id)
  on conflict (tenant_id, catalog_level_id) where catalog_level_id is not null
  do update set course_id = excluded.course_id, name = excluded.name, is_active = true
  returning id into resolved_level_id;

  select exists (
    select 1 from public.subjects s where s.tenant_id = p_tenant_id
      and s.course_id = resolved_course_id and s.name = catalog_subject.name
      and s.catalog_subject_id is null
  ) into has_subject_collision;
  insert into public.subjects (
    tenant_id, course_id, course_level_id, name, catalog_subject_id
  ) values (
    p_tenant_id, resolved_course_id, resolved_level_id,
    catalog_subject.name, catalog_subject.id
  )
  on conflict (tenant_id, catalog_subject_id) where catalog_subject_id is not null
  do update set course_id = excluded.course_id,
    course_level_id = excluded.course_level_id,
    name = excluded.name
  returning id into resolved_subject_id;

  insert into public.institution_offerings (tenant_id, catalog_subject_id)
  values (p_tenant_id, catalog_subject.id)
  on conflict (tenant_id, catalog_subject_id) do nothing;
  return query select resolved_course_id, resolved_subject_id,
    has_course_collision, has_subject_collision;
end;
$$;

revoke all on function public.provision_catalog_subject(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.provision_catalog_subject(uuid, uuid) to service_role;
