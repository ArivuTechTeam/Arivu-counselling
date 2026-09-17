-- ============================================================================
-- Migration 39 — Decouple backend provisioning from the signup trigger
-- Apply after migration-38-repair-auth-profile-trigger.sql.
--
-- Institution admins and teachers are created by the protected backend using
-- the Supabase service role. Their app_metadata contains the trusted
-- provisioned_by_backend marker. Do not make those Auth transactions depend on
-- the public student-signup trigger; the backend creates the authoritative
-- profile immediately after Auth succeeds and rolls the identity back if that
-- profile write fails.
-- ============================================================================

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  google_oauth_signup boolean;
begin
  if coalesce(
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
    'student'::public.user_role,
    nullif(trim(new.raw_user_meta_data->>'full_name'), '')
  );

  insert into public.enrollments (tenant_id, profile_id, course_id)
  values (selected_tenant, new.id, requested_course)
  on conflict (profile_id, course_id) do nothing;

  return new;
end;
$$;

alter function public.handle_new_user() owner to postgres;
revoke all on function public.handle_new_user() from public, anon, authenticated, service_role;
grant execute on function public.handle_new_user() to supabase_auth_admin;

-- The trigger was restored by migration 38. Recreate it here as an idempotent
-- guard in case a project applied the function repair manually.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================================
-- END OF MIGRATION 39
-- ============================================================================
