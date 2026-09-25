-- Migration 62 — serialize each student's contact submissions so the
-- 60-second cooldown also holds for simultaneous requests.
-- Apply after migration 60, before deploying the matching contact API.
begin;

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
  -- The backend supplies the verified identity. Lock that student's profile
  -- until this transaction ends, so a concurrent request cannot pass the
  -- same recent-request check before the first insert commits.
  perform 1 from public.profiles profile
  where profile.id = p_student_id
    and profile.tenant_id = p_tenant_id
    and profile.role = 'student'
  for update;
  if not found then
    raise exception 'student_profile_not_found' using errcode = 'P0002';
  end if;

  request_time := clock_timestamp();
  select request.created_at into recent_at
  from public.student_contact_requests request
  where request.tenant_id = p_tenant_id
    and request.student_id = p_student_id
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
    tenant_id, student_id, reference, kind, category, routed_to, message, rating
  ) values (
    p_tenant_id, p_student_id, p_reference, p_kind, p_category, p_routed_to,
    p_message, p_rating
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

revoke all on function public.submit_student_contact(
  uuid, uuid, text, text, text, text, text, integer
) from public, anon, authenticated;
grant execute on function public.submit_student_contact(
  uuid, uuid, text, text, text, text, text, integer
) to service_role;

commit;
notify pgrst, 'reload schema';
