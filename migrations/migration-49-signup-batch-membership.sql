-- Migration 49 — Signup batch membership (Phase 6.1)
-- Apply after migration 48. Extends handle_new_user so a student who selects a
-- batch at signup is added to it atomically with their course enrollment. The
-- batch_id is validated against the enrolling course + tenant (+ active status),
-- so a crafted metadata value cannot join an arbitrary batch. With no/invalid
-- batch_id, signup behaves exactly as before (no membership, no error).
--
-- The body below is the current handle_new_user reproduced verbatim, with ONLY
-- the batch block added before `return new`. create-or-replace preserves the
-- function's owner/grants and the existing on_auth_user_created trigger.
begin;

create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  requested_batch uuid;
  google_oauth_signup boolean;
begin
  -- Supabase Auth inserts user_metadata with auth.users, then applies custom
  -- app_metadata later. This routing hint only skips trigger provisioning;
  -- the protected backend still creates the authoritative profile.
  if coalesce(
    new.raw_user_meta_data->>'_backend_provisioning_intent', 'false'
  ) = 'true' or coalesce(
    new.raw_app_meta_data->>'provisioned_by_backend', 'false'
  ) = 'true' then
    return new;
  end if;

  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;
  google_oauth_signup :=
    coalesce(new.raw_app_meta_data->>'provider', '') = 'google'
    or (coalesce(new.raw_app_meta_data->'providers', '[]'::jsonb) ? 'google');

  if requested_course is null then
    if google_oauth_signup then
      return new;
    end if;
    raise exception 'A valid course is required for public signup';
  end if;
  select c.tenant_id into selected_tenant
  from public.courses c
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = requested_course;
  if selected_tenant is null then
    raise exception 'A valid course is required for public signup';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    selected_tenant,
    'student'::user_role,
    new.raw_user_meta_data->>'full_name'
  );

  insert into public.enrollments (tenant_id, profile_id, course_id)
  values (selected_tenant, new.id, requested_course)
  on conflict (profile_id, course_id) do nothing;

  -- Optional batch selected at signup. Join ONLY a batch that belongs to the
  -- same enrolling course + tenant and is active; otherwise skip silently.
  requested_batch := nullif(new.raw_user_meta_data->>'batch_id', '')::uuid;
  if requested_batch is not null and exists (
    select 1 from public.batches b
    where b.id = requested_batch
      and b.course_id = requested_course
      and b.tenant_id = selected_tenant
      and b.status = 'active'
  ) then
    insert into public.batch_memberships (tenant_id, batch_id, profile_id, membership_role)
    values (selected_tenant, requested_batch, new.id, 'student')
    on conflict (tenant_id, batch_id, profile_id) do nothing;
  end if;

  return new;
end;
$$;

commit;
notify pgrst, 'reload schema';
