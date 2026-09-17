-- ============================================================================
-- Migration 38 — Repair Auth profile provisioning trigger
-- Apply after migration-37-student-attempt-snapshots.sql.
--
-- Supabase Auth runs auth.users triggers as supabase_auth_admin. Recreate the
-- profile trigger as a postgres-owned SECURITY DEFINER function, pin an empty
-- search path, fully qualify every application object, and explicitly grant
-- only the Auth database role permission to invoke it. This repairs projects
-- where owner or privilege drift causes Auth API `unexpected_failure` errors.
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
  trusted_provisioning boolean;
  google_oauth_signup boolean;
begin
  trusted_provisioning := coalesce(
    new.raw_app_meta_data->>'provisioned_by_backend', 'false'
  ) = 'true';
  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;
  google_oauth_signup :=
    coalesce(new.raw_app_meta_data->>'provider', '') = 'google'
    or (coalesce(new.raw_app_meta_data->'providers', '[]'::jsonb) ? 'google');

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
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    selected_tenant,
    'student'::public.user_role,
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

alter function public.handle_new_user() owner to postgres;
revoke all on function public.handle_new_user() from public, anon, authenticated, service_role;
grant execute on function public.handle_new_user() to supabase_auth_admin;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

do $$
declare
  function_owner text;
  is_security_definer boolean;
begin
  select pg_get_userbyid(p.proowner), p.prosecdef
  into function_owner, is_security_definer
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  where n.nspname = 'public' and p.proname = 'handle_new_user';

  if function_owner <> 'postgres' or not is_security_definer then
    raise exception 'handle_new_user ownership/security configuration is invalid';
  end if;
end;
$$;

-- ============================================================================
-- END OF MIGRATION 38
-- ============================================================================
