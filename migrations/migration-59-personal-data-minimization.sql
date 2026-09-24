-- Migration 59 — remove raw AI payload logging and extend account erasure.
-- Apply after migration 58.
begin;

-- Prompts and responses can contain complete uploaded documents. Cost and
-- health monitoring needs only the metadata that remains on this table.
alter table public.api_call_logs
  drop column if exists raw_request,
  drop column if exists raw_response;

comment on table public.api_call_logs is
  'Metadata-only AI provider usage log. Prompts and responses are not persisted.';

create or replace function public.anonymize_account_data(
  p_user_id uuid,
  p_tenant_id uuid
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.profiles profile
    where profile.id = p_user_id and profile.tenant_id = p_tenant_id
  ) then
    raise exception 'account_not_found' using errcode = 'P0002';
  end if;

  delete from public.quiz_attempts
  where tenant_id = p_tenant_id and student_id = p_user_id;
  delete from public.practice_sessions
  where tenant_id = p_tenant_id and student_id = p_user_id;
  delete from public.bookmarks
  where tenant_id = p_tenant_id and student_id = p_user_id;
  delete from public.revised_topics
  where tenant_id = p_tenant_id and student_id = p_user_id;
  delete from public.enrollments
  where tenant_id = p_tenant_id and profile_id = p_user_id;
  delete from public.teacher_subjects
  where tenant_id = p_tenant_id and teacher_id = p_user_id;
  delete from public.batch_memberships
  where tenant_id = p_tenant_id and profile_id = p_user_id;
  delete from public.ai_rate_limits
  where tenant_id = p_tenant_id and user_id = p_user_id;
  delete from public.events
  where tenant_id = p_tenant_id and actor_id = p_user_id;
  delete from public.quiz_copy_requests
  where tenant_id = p_tenant_id and actor_id = p_user_id;

  -- Erase transient prompts, extracted source text, checkpoints, and provider
  -- records tied to this user's uploads before authorship is anonymized.
  delete from public.api_call_logs logs
  where logs.tenant_id = p_tenant_id and (
    logs.document_id in (
      select id from public.documents
      where tenant_id = p_tenant_id and uploaded_by = p_user_id
    ) or logs.job_id in (
      select id from public.quiz_generation_jobs
      where tenant_id = p_tenant_id and created_by = p_user_id
    )
  );
  delete from public.document_chunks chunks
  where chunks.tenant_id = p_tenant_id and chunks.document_id in (
    select id from public.documents
    where tenant_id = p_tenant_id and uploaded_by = p_user_id
  );
  update public.ai_extraction_jobs jobs
  set raw_output = null, error_message = null
  where jobs.tenant_id = p_tenant_id and jobs.document_id in (
    select id from public.documents
    where tenant_id = p_tenant_id and uploaded_by = p_user_id
  );
  delete from public.faculty_jobs
  where tenant_id = p_tenant_id and created_by = p_user_id;
  delete from public.quiz_generation_jobs
  where tenant_id = p_tenant_id and created_by = p_user_id;

  -- Retain institution-owned teaching records without author identity or the
  -- user's supplied filename/fingerprint.
  update public.documents
  set uploaded_by = null,
      original_filename = case
        when file_type is not null and file_type <> ''
          then 'Deleted user upload.' || file_type
        else 'Deleted user upload'
      end,
      content_hash = null,
      error_message = null
  where tenant_id = p_tenant_id and uploaded_by = p_user_id;
  update public.questions set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;
  update public.questions set reviewed_by = null
  where tenant_id = p_tenant_id and reviewed_by = p_user_id;
  update public.quiz_sets set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;
  update public.batches set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;
  update public.scoring_policies set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;
  update public.challenges
  set creator_id = null, creator_name = 'Deleted user'
  where tenant_id = p_tenant_id and creator_id = p_user_id;
  update public.profiles
  set full_name = null, avatar_url = null, must_change_password = false
  where id = p_user_id and tenant_id = p_tenant_id;
end;
$$;

revoke all on function public.anonymize_account_data(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.anonymize_account_data(uuid, uuid)
  to service_role;

commit;
