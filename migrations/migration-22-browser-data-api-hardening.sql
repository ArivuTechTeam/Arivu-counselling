-- ============================================================================
-- Migration 22 — Browser Data API hardening
-- Apply after migration-21-fix-google-signup-ambiguous-column.sql.
--
-- The web app uses Supabase directly only for Auth, the current user's profile,
-- and complete_google_signup(). All quiz/content/analytics operations go through
-- FastAPI. Deny browser roles direct table access so a user cannot bypass the
-- answer-stripping and ownership checks implemented by the backend.
-- ============================================================================

-- A signed-in user needs only their own profile row for dashboard routing.
drop policy if exists "see own tenant's profiles" on public.profiles;
drop policy if exists "read own profile" on public.profiles;
create policy "read own profile" on public.profiles
  for select to authenticated
  using (id = auth.uid());

revoke all on table public.profiles from anon, authenticated;
grant select on table public.profiles to authenticated;
grant update (full_name, avatar_url) on table public.profiles to authenticated;

-- These tables are backend-only. In particular, questions contains
-- correct_answer/explanation and quiz_variant_questions exposes the mapping
-- needed to enumerate a live quiz's answers. RLS remains enabled as a second
-- layer, but table privileges stop PostgREST access before policies are used.
revoke all on table
  public.tenants,
  public.courses,
  public.subjects,
  public.enrollments,
  public.teacher_subjects,
  public.chapters,
  public.topics,
  public.documents,
  public.ai_extraction_jobs,
  public.questions,
  public.quiz_sets,
  public.quiz_variants,
  public.quiz_variant_questions,
  public.quiz_attempts,
  public.attempt_answers,
  public.ai_explanations,
  public.tenant_usage,
  public.plan_limits,
  public.ai_rate_limits,
  public.events,
  public.practice_sessions,
  public.practice_answers,
  public.bookmarks,
  public.revised_topics,
  public.challenges
from anon, authenticated;

-- Views normally run with their owner's privileges. Make them honor the
-- caller's RLS context and keep them out of the browser Data API entirely.
alter view public.v_student_topic_accuracy set (security_invoker = true);
alter view public.v_quiz_question_analysis set (security_invoker = true);
revoke all on table
  public.v_student_topic_accuracy,
  public.v_quiz_question_analysis
from anon, authenticated;

-- Supabase grants privileges on newly-created public tables by default in many
-- projects. Future application tables should also start backend-only.
alter default privileges in schema public
  revoke all on tables from anon, authenticated;

-- Keep the one browser-facing database function explicit. It derives tenant
-- and student role server-side and is required only after Google OAuth.
revoke all on function public.complete_google_signup(uuid) from public, anon;
grant execute on function public.complete_google_signup(uuid) to authenticated;

-- This trigger function should only run from the auth.users trigger.
revoke all on function public.handle_new_user() from public, anon, authenticated;

notify pgrst, 'reload schema';

-- ============================================================================
-- END OF MIGRATION 22
-- ============================================================================
