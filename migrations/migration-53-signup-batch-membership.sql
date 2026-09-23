-- Migration 53 — Level-aware student signup with optional batch membership.
-- Extends the current Course -> Level signup functions; it must not regress
-- students to course-wide enrollment.
begin;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  requested_level uuid;
  requested_batch uuid;
  google_oauth_signup boolean;
begin
  if coalesce(new.raw_user_meta_data->>'_backend_provisioning_intent', 'false') = 'true'
     or coalesce(new.raw_app_meta_data->>'provisioned_by_backend', 'false') = 'true' then
    return new;
  end if;

  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;
  requested_level := nullif(new.raw_user_meta_data->>'course_level_id', '')::uuid;
  requested_batch := nullif(new.raw_user_meta_data->>'batch_id', '')::uuid;
  google_oauth_signup :=
    coalesce(new.raw_app_meta_data->>'provider', '') = 'google'
    or (coalesce(new.raw_app_meta_data->'providers', '[]'::jsonb) ? 'google');

  if requested_course is null or requested_level is null then
    if google_oauth_signup then return new; end if;
    raise exception 'A valid course and level are required for public signup';
  end if;

  select c.tenant_id into selected_tenant
  from public.courses c
  join public.course_levels l
    on l.course_id = c.id and l.tenant_id = c.tenant_id and l.is_active = true
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = requested_course and l.id = requested_level;
  if selected_tenant is null then
    raise exception 'A valid course and level are required for public signup';
  end if;

  if requested_batch is not null and not exists (
    select 1 from public.batches b
    where b.id = requested_batch
      and b.tenant_id = selected_tenant
      and b.course_id = requested_course
      and b.course_level_id = requested_level
      and b.status = 'active'
  ) then
    raise exception 'The selected batch is not available for this course and level';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (new.id, selected_tenant, 'student'::public.user_role,
          new.raw_user_meta_data->>'full_name');
  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, new.id, requested_course, requested_level)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;

  if requested_batch is not null then
    insert into public.batch_memberships
      (tenant_id, batch_id, profile_id, membership_role)
    values (selected_tenant, requested_batch, new.id, 'student')
    on conflict (tenant_id, batch_id, profile_id)
    do update set active = true;
  end if;
  return new;
end;
$$;

alter function public.handle_new_user() owner to postgres;
revoke all on function public.handle_new_user()
  from public, anon, authenticated, service_role;
grant execute on function public.handle_new_user() to supabase_auth_admin;

drop function if exists public.complete_google_signup(uuid, uuid);

create or replace function public.complete_google_signup(
  p_course_id uuid,
  p_course_level_id uuid,
  p_batch_id uuid
)
returns table (
  out_tenant_id uuid,
  out_role public.user_role,
  out_course_id uuid,
  out_course_level_id uuid,
  out_batch_id uuid
)
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
  if current_user_id is null then raise exception 'Authentication is required'; end if;
  select u.raw_user_meta_data, u.raw_app_meta_data into user_metadata, app_metadata
  from auth.users u where u.id = current_user_id for update;
  if not found then raise exception 'Authenticated user not found'; end if;
  if coalesce(app_metadata->>'provider', '') <> 'google'
     and not (coalesce(app_metadata->'providers', '[]'::jsonb) ? 'google') then
    raise exception 'Google authentication is required';
  end if;

  select p.tenant_id, p.role into existing_tenant, existing_role
  from public.profiles p where p.id = current_user_id;
  if found then
    return query select existing_tenant, existing_role,
      null::uuid, null::uuid, null::uuid;
    return;
  end if;

  select c.tenant_id into selected_tenant
  from public.courses c
  join public.course_levels l
    on l.course_id = c.id and l.tenant_id = c.tenant_id and l.is_active = true
  join public.tenants t on t.id = c.tenant_id and t.is_active = true
  where c.id = p_course_id and l.id = p_course_level_id;
  if selected_tenant is null then
    raise exception 'A valid course and level are required for Google signup';
  end if;

  if p_batch_id is not null and not exists (
    select 1 from public.batches b
    where b.id = p_batch_id
      and b.tenant_id = selected_tenant
      and b.course_id = p_course_id
      and b.course_level_id = p_course_level_id
      and b.status = 'active'
  ) then
    raise exception 'The selected batch is not available for this course and level';
  end if;

  insert into public.profiles (id, tenant_id, role, full_name)
  values (current_user_id, selected_tenant, 'student'::public.user_role,
          nullif(trim(coalesce(user_metadata->>'full_name', user_metadata->>'name')), ''));
  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, current_user_id, p_course_id, p_course_level_id)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;
  if p_batch_id is not null then
    insert into public.batch_memberships
      (tenant_id, batch_id, profile_id, membership_role)
    values (selected_tenant, p_batch_id, current_user_id, 'student')
    on conflict (tenant_id, batch_id, profile_id)
    do update set active = true;
  end if;
  return query select selected_tenant, 'student'::public.user_role,
    p_course_id, p_course_level_id, p_batch_id;
end;
$$;

revoke all on function public.complete_google_signup(uuid, uuid, uuid)
  from public, anon;
grant execute on function public.complete_google_signup(uuid, uuid, uuid)
  to authenticated;

commit;
notify pgrst, 'reload schema';
