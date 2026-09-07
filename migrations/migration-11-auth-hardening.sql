-- ============================================================================
-- Migration 11 — Harden profile provisioning and profile updates
-- ============================================================================
-- Public Auth sign-up metadata is controlled by the caller. Never copy a role
-- or tenant from it into the authorization profile. Public tenant selection is
-- derived from the selected course; protected backend provisioning is marked
-- in app_metadata, which browser clients cannot write.

alter table profiles
  add column if not exists must_change_password boolean not null default false;

update profiles p
set must_change_password = true
from auth.users u
where u.id = p.id
  and coalesce(u.raw_user_meta_data->>'must_change_password', 'false') = 'true'
  and not p.must_change_password;

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

  -- Every untrusted/public signup starts as a student. Teacher and admin roles
  -- are assigned only by authenticated backend provisioning endpoints.
  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    selected_tenant,
    'student'::user_role,
    nullif(trim(new.raw_user_meta_data->>'full_name'), '')
  );

  if requested_course is not null then
    if not exists (
      select 1 from public.courses
      where id = requested_course and tenant_id = selected_tenant
    ) then
      raise exception 'Course does not belong to the selected institution';
    end if;

    insert into public.enrollments (tenant_id, profile_id, course_id)
    values (selected_tenant, new.id, requested_course)
    on conflict (profile_id, course_id) do nothing;
  end if;

  return new;
end;
$$;

-- A user may edit presentation fields on their own row, but the resulting row
-- must retain the authoritative tenant and role visible at the start of the
-- request. Admin account management is performed by the backend service role.
drop policy if exists "update own profile or admin manages tenant profiles" on profiles;
drop policy if exists "update own safe profile fields" on profiles;
create policy "update own safe profile fields" on profiles
  for update
  using (id = auth.uid())
  with check (
    id = auth.uid()
    and tenant_id = current_tenant_id()
    and role = current_role_name()
  );

revoke update on table profiles from authenticated;
grant update (full_name, avatar_url) on table profiles to authenticated;

-- Practice sessions mirror quiz_attempts autosave support so every student
-- mode survives refreshes and temporary network loss.
alter table if exists practice_sessions
  add column if not exists autosave_state jsonb not null default '{}'::jsonb;

-- ============================================================================
-- END OF MIGRATION 11
-- ============================================================================
