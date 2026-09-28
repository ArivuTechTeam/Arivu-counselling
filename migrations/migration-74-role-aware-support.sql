-- Migration 74 — extend the private support inbox to teachers and institution
-- administrators while preserving existing student requests and routing.
-- Apply after migration 73 and before deploying the matching API/frontend.
begin;

alter table public.student_contact_requests
  rename column student_id to requester_id;

alter table public.student_contact_requests
  rename constraint student_contact_requests_student_tenant_fkey
  to student_contact_requests_requester_tenant_fkey;

alter index public.student_contact_requests_student_recent_idx
  rename to student_contact_requests_requester_recent_idx;

alter table public.student_contact_requests
  add column requester_role text;

update public.student_contact_requests
set requester_role = 'student'
where requester_role is null;

alter table public.student_contact_requests
  alter column requester_role set not null,
  add constraint student_contact_requests_requester_role_check
    check (requester_role in ('student', 'teacher', 'institution_admin'));

alter table public.student_contact_requests
  drop constraint student_contact_requests_category_check,
  add constraint student_contact_requests_category_check
    check (category in (
      'general', 'feature_idea', 'general_support',
      'course_access', 'quiz_issue', 'app_bug'
    )),
  drop constraint student_contact_requests_route_check,
  add constraint student_contact_requests_route_check check (
    (kind = 'feedback'
      and category in ('general', 'feature_idea', 'app_bug')
      and routed_to = 'platform')
    or
    (kind = 'support' and rating is null and (
      (requester_role = 'student'
        and category in ('course_access', 'quiz_issue')
        and routed_to = 'institution')
      or
      (category in ('general_support', 'app_bug')
        and routed_to = 'platform')
      or
      (requester_role in ('teacher', 'institution_admin')
        and category in ('course_access', 'quiz_issue')
        and routed_to = 'platform')
    ))
  );

create or replace function public.submit_contact_request(
  p_tenant_id uuid,
  p_requester_id uuid,
  p_requester_role text,
  p_reference text,
  p_kind text,
  p_category text,
  p_routed_to text,
  p_message text,
  p_rating integer
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  request_time timestamptz;
  recent_at timestamptz;
  saved_reference text;
  saved_route text;
  saved_status text;
begin
  if p_requester_role not in ('student', 'teacher', 'institution_admin') then
    raise exception 'support_role_not_allowed' using errcode = 'PT403';
  end if;

  -- Serialize submissions per verified profile so simultaneous requests cannot
  -- both pass the cooldown. Role and tenant must match the authoritative row.
  perform 1 from public.profiles profile
  where profile.id = p_requester_id
    and profile.tenant_id = p_tenant_id
    and profile.role::text = p_requester_role
  for update;
  if not found then
    raise exception 'support_profile_not_found' using errcode = 'P0002';
  end if;

  request_time := clock_timestamp();
  select request.created_at into recent_at
  from public.student_contact_requests request
  where request.tenant_id = p_tenant_id
    and request.requester_id = p_requester_id
  order by request.created_at desc
  limit 1;

  if recent_at is not null and recent_at > request_time - interval '60 seconds' then
    return jsonb_build_object(
      'allowed', false,
      'retry_after_seconds', greatest(
        1,
        ceil(extract(epoch from (recent_at + interval '60 seconds' - request_time)))::integer
      )
    );
  end if;

  insert into public.student_contact_requests (
    tenant_id, requester_id, requester_role, reference, kind, category,
    routed_to, message, rating
  ) values (
    p_tenant_id, p_requester_id, p_requester_role, p_reference, p_kind,
    p_category, p_routed_to, p_message, p_rating
  ) returning reference, routed_to, status
    into saved_reference, saved_route, saved_status;

  return jsonb_build_object(
    'allowed', true,
    'reference', saved_reference,
    'routed_to', saved_route,
    'status', saved_status
  );
end;
$$;

revoke all on function public.submit_contact_request(
  uuid, uuid, text, text, text, text, text, text, integer
) from public, anon, authenticated;
grant execute on function public.submit_contact_request(
  uuid, uuid, text, text, text, text, text, text, integer
) to service_role;

-- Compatibility wrapper: migration 74 can be applied before the new API
-- without interrupting the already-deployed student submission endpoint.
create or replace function public.submit_student_contact(
  p_tenant_id uuid,
  p_student_id uuid,
  p_reference text,
  p_kind text,
  p_category text,
  p_routed_to text,
  p_message text,
  p_rating integer
)
returns jsonb
language sql
security invoker
set search_path = ''
as $$
  select public.submit_contact_request(
    p_tenant_id, p_student_id, 'student', p_reference, p_kind, p_category,
    p_routed_to, p_message, p_rating
  );
$$;

revoke all on function public.submit_student_contact(
  uuid, uuid, text, text, text, text, text, integer
) from public, anon, authenticated;
grant execute on function public.submit_student_contact(
  uuid, uuid, text, text, text, text, text, integer
) to service_role;

commit;
notify pgrst, 'reload schema';
