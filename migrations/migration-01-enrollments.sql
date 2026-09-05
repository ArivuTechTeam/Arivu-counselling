-- ============================================================================
-- Migration 01 — Course enrollment (students AND teachers) + quiz targeting
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
-- Safe to run even if you ran an earlier version — enrollments is recreated
-- (it holds no important data yet).
-- ============================================================================


-- ── 1. enrollments: maps ANY user (student or teacher) to a course ─────────
drop table if exists enrollments cascade;
create table enrollments (
  id uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id),
  profile_id uuid not null references profiles(id) on delete cascade,
  course_id  uuid not null references courses(id)  on delete cascade,
  created_at timestamptz not null default now(),
  unique (profile_id, course_id)
);
create index idx_enrollments_tenant  on enrollments(tenant_id);
create index idx_enrollments_profile on enrollments(profile_id);
create index idx_enrollments_course  on enrollments(course_id);


-- ── 2. tag quiz sets with a subject (for student targeting) ────────────────
alter table quiz_sets add column if not exists subject_id uuid references subjects(id);
create index if not exists idx_quizsets_subject on quiz_sets(subject_id);


-- ── 3. Row Level Security ──────────────────────────────────────────────────
alter table enrollments enable row level security;

create policy "read own enrollment or staff" on enrollments
  for select using (
    tenant_id = current_tenant_id()
    and (profile_id = auth.uid() or is_staff() or is_super_admin())
  );

create policy "staff manage enrollments" on enrollments
  for all
  using      (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());


-- ── 4. Auto-create profile AND enrollment on signup ────────────────────────
-- Extends the existing handle_new_user trigger: if the signup metadata carries
-- a course_id, the new user is enrolled/mapped to that course automatically.
create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  trusted_provisioning boolean;
begin
  trusted_provisioning := coalesce(
    new.raw_app_meta_data->>'provisioned_by_backend', 'false'
  ) = 'true';
  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;

  if trusted_provisioning then
    selected_tenant := (new.raw_user_meta_data->>'tenant_id')::uuid;
    if not exists (
      select 1 from public.tenants
      where id = selected_tenant and is_active = true
    ) then
      raise exception 'A valid active institution is required';
    end if;
  else
    if requested_course is null then
      raise exception 'A valid course is required for public signup';
    end if;
    select c.tenant_id into selected_tenant
    from public.courses c
    join public.tenants t on t.id = c.tenant_id and t.is_active = true
    where c.id = requested_course;
    if selected_tenant is null then
      raise exception 'A valid course is required for public signup';
    end if;
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    selected_tenant,
    'student'::user_role,
    new.raw_user_meta_data->>'full_name'
  );

  if requested_course is not null then
    if not exists (
      select 1 from public.courses
      where id = requested_course and tenant_id = selected_tenant
    ) then
      raise exception 'Course does not belong to the selected institution';
    end if;
    insert into public.enrollments (tenant_id, profile_id, course_id)
    values (
      selected_tenant,
      new.id,
      requested_course
    )
    on conflict (profile_id, course_id) do nothing;
  end if;

  return new;
end;
$$;

-- ============================================================================
-- END OF MIGRATION 01
-- ============================================================================
