-- ============================================================================
-- Migration 14 — Safe Google OAuth student onboarding
-- ============================================================================
-- Google creates auth.users before the application can ask a new user for a
-- course. Permit that one incomplete state, then let the authenticated user
-- finish onboarding through a security-definer function that derives the
-- tenant from a real active course and always assigns the student role.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
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
      -- OAuth providers cannot receive our course_id as trusted signup
      -- metadata. The callback completes this Google user's profile through
      -- complete_google_signup after the user selects a validated course.
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

create or replace function public.complete_google_signup(p_course_id uuid)
returns table (tenant_id uuid, role public.user_role, course_id uuid)
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

revoke all on function public.complete_google_signup(uuid)
  from public, anon;
grant execute on function public.complete_google_signup(uuid)
  to authenticated;

-- ============================================================================
-- END OF MIGRATION 14
-- ============================================================================
