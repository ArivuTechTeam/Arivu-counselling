-- ============================================================================
-- Migration 12 — Explicit teacher-to-subject assignments
-- Apply after migration-11-auth-hardening.sql and before deploying code that
-- reads teacher_subjects.
-- ============================================================================

-- Composite uniqueness lets the foreign keys below enforce that the teacher,
-- subject and assignment all belong to the same tenant, including writes made
-- through the service-role client.
create unique index if not exists uq_profiles_id_tenant
  on public.profiles (id, tenant_id);
create unique index if not exists uq_subjects_id_tenant
  on public.subjects (id, tenant_id);

create table if not exists public.teacher_subjects (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  teacher_id uuid not null,
  subject_id uuid not null,
  created_at timestamptz not null default now(),
  constraint teacher_subjects_teacher_tenant_fk
    foreign key (teacher_id, tenant_id)
    references public.profiles(id, tenant_id) on delete cascade,
  constraint teacher_subjects_subject_tenant_fk
    foreign key (subject_id, tenant_id)
    references public.subjects(id, tenant_id) on delete cascade,
  constraint teacher_subjects_teacher_subject_key unique (teacher_id, subject_id)
);

-- If an earlier draft of this table was applied, add the tenant-consistency
-- constraints that CREATE TABLE IF NOT EXISTS would otherwise skip.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'teacher_subjects_teacher_tenant_fk'
      and conrelid = 'public.teacher_subjects'::regclass
  ) then
    alter table public.teacher_subjects
      add constraint teacher_subjects_teacher_tenant_fk
      foreign key (teacher_id, tenant_id)
      references public.profiles(id, tenant_id) on delete cascade;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname = 'teacher_subjects_subject_tenant_fk'
      and conrelid = 'public.teacher_subjects'::regclass
  ) then
    alter table public.teacher_subjects
      add constraint teacher_subjects_subject_tenant_fk
      foreign key (subject_id, tenant_id)
      references public.subjects(id, tenant_id) on delete cascade;
  end if;
end;
$$;

create index if not exists idx_teacher_subjects_tenant
  on public.teacher_subjects(tenant_id);
create index if not exists idx_teacher_subjects_teacher
  on public.teacher_subjects(teacher_id);
create index if not exists idx_teacher_subjects_subject
  on public.teacher_subjects(subject_id);

alter table public.teacher_subjects enable row level security;

-- Teachers must not be able to rewrite enrolments directly. Institution-admin
-- changes go through tenant-scoped backend endpoints; student self-enrolment is
-- handled only by the trusted signup trigger.
drop policy if exists "staff manage enrollments" on public.enrollments;
drop policy if exists "institution admins manage enrollments" on public.enrollments;
create policy "institution admins manage enrollments" on public.enrollments
  for all to authenticated
  using (
    tenant_id = current_tenant_id()
    and current_role_name() = 'institution_admin'
  )
  with check (
    tenant_id = current_tenant_id()
    and current_role_name() = 'institution_admin'
  );

drop policy if exists "read permitted teacher subjects" on public.teacher_subjects;
create policy "read permitted teacher subjects" on public.teacher_subjects
  for select to authenticated
  using (
    is_super_admin()
    or (
      tenant_id = current_tenant_id()
      and (
        teacher_id = auth.uid()
        or current_role_name() = 'institution_admin'
      )
    )
  );

-- Preserve every existing teacher's current access during rollout.
insert into public.teacher_subjects (tenant_id, teacher_id, subject_id)
select distinct p.tenant_id, p.id, s.id
from public.profiles p
join public.enrollments e
  on e.profile_id = p.id and e.tenant_id = p.tenant_id
join public.subjects s
  on s.course_id = e.course_id and s.tenant_id = p.tenant_id
where p.role = 'teacher'
on conflict (teacher_id, subject_id) do nothing;

-- Replacing assignments and rebuilding the derived course enrolments must be
-- atomic. The backend invokes this RPC with the service-role client after it
-- has authenticated and tenant-scoped the institution admin.
create or replace function public.replace_teacher_subjects(
  p_tenant_id uuid,
  p_teacher_id uuid,
  p_subject_ids uuid[] default '{}'::uuid[]
)
returns uuid[]
language plpgsql
security invoker
set search_path = ''
as $$
declare
  normalized_ids uuid[];
begin
  select coalesce(array_agg(subject_id order by first_position), '{}'::uuid[])
  into normalized_ids
  from (
    select subject_id, min(position) as first_position
    from unnest(coalesce(p_subject_ids, '{}'::uuid[]))
      with ordinality as requested(subject_id, position)
    group by subject_id
  ) deduplicated;

  if cardinality(normalized_ids) > 500 then
    raise exception 'A teacher may have at most 500 assigned subjects';
  end if;

  if not exists (
    select 1 from public.profiles
    where id = p_teacher_id
      and tenant_id = p_tenant_id
      and role = 'teacher'
  ) then
    raise exception 'Teacher not found in this institution';
  end if;

  if exists (
    select 1
    from unnest(normalized_ids) requested(subject_id)
    left join public.subjects s
      on s.id = requested.subject_id and s.tenant_id = p_tenant_id
    where s.id is null
  ) then
    raise exception 'One or more subjects do not belong to this institution';
  end if;

  delete from public.teacher_subjects
  where teacher_id = p_teacher_id and tenant_id = p_tenant_id;

  insert into public.teacher_subjects (tenant_id, teacher_id, subject_id)
  select p_tenant_id, p_teacher_id, subject_id
  from unnest(normalized_ids) requested(subject_id);

  -- enrollments remains available to older reporting code, but it is derived
  -- from assignments and is no longer an authorization source for teachers.
  delete from public.enrollments
  where profile_id = p_teacher_id and tenant_id = p_tenant_id;

  insert into public.enrollments (tenant_id, profile_id, course_id)
  select distinct p_tenant_id, p_teacher_id, s.course_id
  from public.subjects s
  where s.tenant_id = p_tenant_id and s.id = any(normalized_ids)
  on conflict (profile_id, course_id) do nothing;

  return normalized_ids;
end;
$$;

revoke all on function public.replace_teacher_subjects(uuid, uuid, uuid[])
  from public, anon, authenticated;
grant execute on function public.replace_teacher_subjects(uuid, uuid, uuid[])
  to service_role;

-- ============================================================================
-- END OF MIGRATION 12
-- ============================================================================
