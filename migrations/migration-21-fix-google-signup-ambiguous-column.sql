-- Migration 21 — Fix "column reference course_id is ambiguous" in
-- complete_google_signup (introduced in migration-14).
-- Apply after migration-20-teacher-deletion-content-retention.sql.
--
-- `returns table (tenant_id uuid, role public.user_role, course_id uuid)`
-- implicitly declares tenant_id/role/course_id as PL/pgSQL variables in the
-- function's own scope. Those names collide with real columns on
-- public.profiles (tenant_id, role) and public.enrollments (tenant_id,
-- course_id), so Postgres's default `plpgsql.variable_conflict = error`
-- can't tell whether a bare reference inside the function body (the
-- `on conflict (profile_id, course_id)` target list in particular) means the
-- table column or the OUT parameter, and raises rather than guessing.
--
-- Fix: rename the OUT parameters so they no longer collide with any real
-- column name. The frontend (`app/auth/callback/page.tsx`) only checks this
-- RPC's `error`, never its returned columns, so the rename has no callers to
-- update.
--
-- Renaming OUT parameters changes the function's row type, which
-- `create or replace function` cannot do in place — drop it first.
drop function if exists public.complete_google_signup(uuid);

create function public.complete_google_signup(p_course_id uuid)
returns table (out_tenant_id uuid, out_role public.user_role, out_course_id uuid)
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
  if current_user_id is null then
    raise exception 'Authentication is required';
  end if;

  -- Lock this Auth row so two callback tabs cannot assign different courses.
  select u.raw_user_meta_data, u.raw_app_meta_data
  into user_metadata, app_metadata
  from auth.users u
  where u.id = current_user_id
  for update;

  if not found then
    raise exception 'Authenticated user not found';
  end if;

  if coalesce(app_metadata->>'provider', '') <> 'google'
     and not (coalesce(app_metadata->'providers', '[]'::jsonb) ? 'google') then
    raise exception 'Google authentication is required';
  end if;

  -- Automatic identity linking may bring an existing password user through
  -- this callback. Never replace that user's tenant, role, or enrollment.
  select p.tenant_id, p.role
  into existing_tenant, existing_role
  from public.profiles p
  where p.id = current_user_id;

  if found then
    return query select existing_tenant, existing_role, null::uuid;
    return;
  end if;

  select c.tenant_id into selected_tenant
  from public.courses c
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = p_course_id;

  if selected_tenant is null then
    raise exception 'A valid course is required for Google signup';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    current_user_id,
    selected_tenant,
    'student'::public.user_role,
    nullif(trim(coalesce(user_metadata->>'full_name', user_metadata->>'name')), '')
  );

  insert into public.enrollments (tenant_id, profile_id, course_id)
  values (selected_tenant, current_user_id, p_course_id)
  on conflict (profile_id, course_id) do nothing;

  return query
    select selected_tenant, 'student'::public.user_role, p_course_id;
end;
$$;

-- ============================================================================
-- END OF MIGRATION 21
-- ============================================================================
