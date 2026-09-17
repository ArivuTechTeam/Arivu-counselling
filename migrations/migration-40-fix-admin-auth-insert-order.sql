-- ============================================================================
-- Migration 40 — Respect Supabase Auth's admin-user insert order
-- Apply after migration-39-decouple-backend-auth-provisioning.sql.
--
-- Supabase Auth constructs and inserts auth.users with user_metadata first,
-- then merges custom app_metadata later in the same transaction. Consequently,
-- an AFTER INSERT trigger cannot see the provisioned_by_backend app_metadata
-- marker. The protected backend now also sends an insert-time routing hint in
-- user_metadata. This hint grants no access: the backend still writes the
-- authoritative public.profiles role and tenant using the service role.
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
  -- app_metadata is retained as the durable trusted marker, but Supabase Auth
  -- applies it after INSERT. user_metadata is available on the inserted row.
  -- A public caller can forge this routing hint only to skip creation of their
  -- own profile; it is never used to assign a role, tenant, or permissions.
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

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================================
-- END OF MIGRATION 40
-- ============================================================================
