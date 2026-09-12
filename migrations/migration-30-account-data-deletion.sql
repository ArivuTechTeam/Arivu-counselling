-- ============================================================================

begin;
-- Migration 30 — Personal-data deletion and authorship anonymization
-- Apply after migration 29.
--
-- The backend calls this service-role-only function before deleting the
-- Supabase Auth identity. Personal activity is erased while institution-owned
-- teaching content remains usable without identifying its former author.
-- ============================================================================

alter table public.challenges
  alter column creator_id drop not null,
  drop constraint if exists challenges_creator_id_fkey,
  add constraint challenges_creator_id_fkey
    foreign key (creator_id) references public.profiles(id) on delete set null;

alter table public.quiz_attempts
  drop constraint if exists quiz_attempts_student_id_fkey,
  add constraint quiz_attempts_student_id_fkey
    foreign key (student_id) references public.profiles(id) on delete cascade;

alter table public.practice_sessions
  drop constraint if exists practice_sessions_student_id_fkey,
  add constraint practice_sessions_student_id_fkey
    foreign key (student_id) references public.profiles(id) on delete cascade;

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
    select 1
    from public.profiles profile
    where profile.id = p_user_id
      and profile.tenant_id = p_tenant_id
  ) then
    raise exception 'account_not_found' using errcode = 'P0002';
  end if;

  -- Attempts, answers, bookmarks, revision state, enrolments, and rate-limit
  -- counters are personal activity and should not survive account deletion.
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

  delete from public.ai_rate_limits
  where tenant_id = p_tenant_id and user_id = p_user_id;

  -- Instrumentation is not an academic record. Remove the actor's event rows
  -- instead of retaining a persistent activity trail keyed to their UUID.
  delete from public.events
  where tenant_id = p_tenant_id and actor_id = p_user_id;

  -- Institution-owned teaching material remains, but all author/reviewer
  -- pointers and user-supplied filenames are removed.
  update public.documents
  set uploaded_by = null,
      original_filename = case
        when file_type is not null and file_type <> ''
          then 'Deleted user upload.' || file_type
        else 'Deleted user upload'
      end,
      content_hash = null
  where tenant_id = p_tenant_id and uploaded_by = p_user_id;

  update public.questions
  set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;

  update public.questions
  set reviewed_by = null
  where tenant_id = p_tenant_id and reviewed_by = p_user_id;

  update public.quiz_sets
  set created_by = null
  where tenant_id = p_tenant_id and created_by = p_user_id;

  update public.challenges
  set creator_id = null,
      creator_name = 'Deleted user'
  where tenant_id = p_tenant_id and creator_id = p_user_id;

  update public.profiles
  set full_name = null,
      avatar_url = null,
      must_change_password = false
  where id = p_user_id and tenant_id = p_tenant_id;
end;
$$;

revoke all on function public.anonymize_account_data(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.anonymize_account_data(uuid, uuid)
  to service_role;

commit;

-- ============================================================================
-- END OF MIGRATION 30
-- ============================================================================
