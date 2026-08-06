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
begin
  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    (new.raw_user_meta_data->>'tenant_id')::uuid,
    (new.raw_user_meta_data->>'role')::user_role,
    new.raw_user_meta_data->>'full_name'
  );

  if coalesce(new.raw_user_meta_data->>'course_id', '') <> '' then
    insert into public.enrollments (tenant_id, profile_id, course_id)
    values (
      (new.raw_user_meta_data->>'tenant_id')::uuid,
      new.id,
      (new.raw_user_meta_data->>'course_id')::uuid
    )
    on conflict (profile_id, course_id) do nothing;
  end if;

  return new;
end;
$$;

-- ============================================================================
-- END OF MIGRATION 01
-- ============================================================================
