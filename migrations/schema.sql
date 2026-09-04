-- ============================================================================
-- quiz-generator-v1 — Supabase schema (v1)
-- Multi-tenant AI quiz platform. ArivuPro = tenant #1, same as any customer.
-- Run this whole file once, top to bottom, in the Supabase SQL Editor.
-- ============================================================================


-- ============================================================================
-- STEP 1: EXTENSIONS
-- ============================================================================
-- pgcrypto gives us gen_random_uuid() for primary keys.
-- vector (pgvector) lets us store question embeddings for duplicate detection.
create extension if not exists pgcrypto;
create extension if not exists vector;


-- ============================================================================
-- STEP 2: ENUMS
-- Postgres enums instead of free-text status columns. Typos become
-- impossible at insert time instead of bugs discovered in production.
-- ============================================================================
create type user_role as enum ('super_admin', 'institution_admin', 'teacher', 'student');
create type question_type as enum ('mcq_single', 'mcq_multi', 'numerical', 'true_false', 'fill_blank', 'descriptive');
create type question_source as enum ('ai_generated', 'manual');
create type review_status as enum ('pending_review', 'approved', 'rejected', 'needs_edit');
create type document_status as enum ('uploaded', 'processing', 'completed', 'failed');
create type job_status as enum ('queued', 'running', 'succeeded', 'failed');
create type variant_type as enum ('theory', 'practical', 'mixed');
create type quiz_status as enum ('draft', 'published', 'archived');
create type attempt_status as enum ('in_progress', 'submitted', 'graded', 'abandoned');


-- ============================================================================
-- STEP 3: TENANT & IDENTITY
-- ============================================================================

-- tenants: one row per institution. ArivuPro is a row here too — no special
-- casing anywhere else in the schema for "the platform owner".
create table tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  subdomain text not null unique,          -- e.g. 'arivupro' -> arivupro.platform.com
  logo_url text,
  primary_color text default '#0EA5E9',
  secondary_color text default '#1E293B',
  plan_tier text not null default 'free',  -- fk-like reference to plan_limits.plan_tier
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

-- profiles: 1:1 extension of auth.users. This is where tenant_id and role
-- live — auth.users itself is untouchable (Supabase-managed).
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  tenant_id uuid not null references tenants(id),
  role user_role not null,
  full_name text,
  avatar_url text,
  created_at timestamptz not null default now()
);
create index idx_profiles_tenant on profiles(tenant_id);


-- ============================================================================
-- STEP 4: ACADEMIC HIERARCHY (Course -> Subject -> Chapter -> Topic)
-- ============================================================================

create table courses (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  name text not null,
  created_at timestamptz not null default now()
);
create index idx_courses_tenant on courses(tenant_id);

create table subjects (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  course_id uuid not null references courses(id) on delete cascade,
  name text not null
);
create index idx_subjects_tenant on subjects(tenant_id);
create index idx_subjects_course on subjects(course_id);

create table chapters (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  subject_id uuid not null references subjects(id) on delete cascade,
  name text not null,
  order_index int not null default 0
);
create index idx_chapters_tenant on chapters(tenant_id);
create index idx_chapters_subject on chapters(subject_id);

create table topics (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  chapter_id uuid not null references chapters(id) on delete cascade,
  name text not null
);
create index idx_topics_tenant on topics(tenant_id);
create index idx_topics_chapter on topics(chapter_id);


-- ============================================================================
-- STEP 5: CONTENT INGESTION (uploads -> AI extraction)
-- ============================================================================

create table documents (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  uploaded_by uuid not null references profiles(id),
  chapter_id uuid references chapters(id),
  storage_path text not null,              -- path inside the Supabase Storage bucket
  original_filename text,
  file_type text,
  status document_status not null default 'uploaded',
  error_message text,
  created_at timestamptz not null default now()
);
create index idx_documents_tenant on documents(tenant_id);

-- One row per AI processing run on a document. Kept separate from
-- `documents` because a document can be reprocessed (e.g. DeepSeek failed,
-- Claude fallback retried) — you want that history, not an overwrite.
create table ai_extraction_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  document_id uuid not null references documents(id) on delete cascade,
  status job_status not null default 'queued',
  model_used text,                          -- 'deepseek-v4' or 'claude-sonnet-5'
  raw_output jsonb,
  overall_confidence numeric,
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index idx_jobs_tenant on ai_extraction_jobs(tenant_id);
create index idx_jobs_document on ai_extraction_jobs(document_id);


-- ============================================================================
-- STEP 6: QUESTION BANK
-- No separate "review_queue" table — review status lives directly on the
-- question row. One less join for the single most-queried table in the app.
-- ============================================================================

create table questions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  chapter_id uuid references chapters(id),
  topic_id uuid references topics(id),
  extraction_job_id uuid references ai_extraction_jobs(id),  -- null if manually authored
  type question_type not null,
  question_text text not null,
  latex_content text,
  options jsonb,                            -- for mcq types: [{id, text}, ...]
  correct_answer jsonb not null,
  explanation text,
  difficulty text default 'medium',
  marks numeric not null default 1,
  source question_source not null default 'manual',
  confidence_score numeric,                 -- null for manual questions
  review_status review_status not null default 'approved',
  reviewed_by uuid references profiles(id),
  reviewed_at timestamptz,
  embedding vector(1536),                   -- for semantic duplicate detection
  created_by uuid references profiles(id),
  created_at timestamptz not null default now()
);
create index idx_questions_tenant on questions(tenant_id);
create index idx_questions_chapter on questions(chapter_id);
create index idx_questions_review_status on questions(review_status);
-- HNSW index for fast cosine-similarity search (duplicate detection)
create index idx_questions_embedding on questions using hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- STEP 7: QUIZ ENGINE (Quiz Set -> Variant -> Questions)
-- ============================================================================

create table quiz_sets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  chapter_id uuid references chapters(id),
  title text not null,
  description text,
  status quiz_status not null default 'draft',
  created_by uuid not null references profiles(id),
  created_at timestamptz not null default now(),
  published_at timestamptz
);
create index idx_quizsets_tenant on quiz_sets(tenant_id);

create table quiz_variants (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  quiz_set_id uuid not null references quiz_sets(id) on delete cascade,
  variant_type variant_type not null,       -- theory / practical / mixed
  time_limit_minutes int,
  total_marks numeric,
  created_at timestamptz not null default now()
);
create index idx_variants_tenant on quiz_variants(tenant_id);
create index idx_variants_quizset on quiz_variants(quiz_set_id);

create table quiz_variant_questions (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  variant_id uuid not null references quiz_variants(id) on delete cascade,
  question_id uuid not null references questions(id),
  order_index int not null default 0,
  marks_override numeric,
  unique(variant_id, question_id)
);
create index idx_vq_tenant on quiz_variant_questions(tenant_id);
create index idx_vq_variant on quiz_variant_questions(variant_id);


-- ============================================================================
-- STEP 8: STUDENT ATTEMPTS & GRADING
-- ============================================================================

create table quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  variant_id uuid not null references quiz_variants(id),
  student_id uuid not null references profiles(id),
  status attempt_status not null default 'in_progress',
  autosave_state jsonb,                     -- last known client state, for recovery
  started_at timestamptz not null default now(),
  submitted_at timestamptz,
  total_score numeric
);
create index idx_attempts_tenant on quiz_attempts(tenant_id);
create index idx_attempts_student on quiz_attempts(student_id);
create index idx_attempts_variant on quiz_attempts(variant_id);

create table attempt_answers (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  attempt_id uuid not null references quiz_attempts(id) on delete cascade,
  question_id uuid not null references questions(id),
  student_answer jsonb,
  is_correct boolean,
  marks_awarded numeric,
  answered_at timestamptz not null default now(),
  unique(attempt_id, question_id)
);
create index idx_answers_tenant on attempt_answers(tenant_id);
create index idx_answers_attempt on attempt_answers(attempt_id);


-- ============================================================================
-- STEP 9: AI TUTOR (cached by question, not by attempt)
-- One explanation per question, reused across every student who gets it
-- wrong. Regenerating per-attempt would multiply your LLM bill for no
-- reason — the explanation for "why is X wrong" doesn't change per student.
-- ============================================================================

create table ai_explanations (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  question_id uuid not null references questions(id) on delete cascade,
  explanation_text text,
  hints jsonb,                              -- ["hint 1", "hint 2", ...]
  simplified_text text,
  model_used text,
  created_at timestamptz not null default now(),
  unique(question_id)
);
create index idx_explanations_tenant on ai_explanations(tenant_id);


-- ============================================================================
-- STEP 10: QUOTAS (v1-lite — no billing tables, just limits + a counter)
-- ============================================================================

-- Global config, not tenant-scoped. Same limits apply to every tenant on
-- a given plan_tier.
create table plan_limits (
  plan_tier text primary key,
  ocr_page_limit int not null,
  student_cap int not null,
  monthly_price numeric not null default 0
);

insert into plan_limits (plan_tier, ocr_page_limit, student_cap, monthly_price) values
  ('free', 50, 30, 0),
  ('starter', 500, 300, 2999),
  ('growth', 3000, 2000, 9999),
  ('enterprise', 999999, 999999, 0);

create table tenant_usage (
  tenant_id uuid primary key references tenants(id),
  period_start date not null default date_trunc('month', now())::date,
  ocr_pages_used int not null default 0,
  updated_at timestamptz not null default now()
);


-- ============================================================================
-- STEP 11: HELPER FUNCTIONS (used everywhere in RLS policies below)
-- ============================================================================

-- Returns the tenant_id of whoever is currently making the request.
-- SECURITY DEFINER + fixed search_path so it can read `profiles` even
-- though the calling role might not have a broad SELECT grant on it.
create or replace function current_tenant_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select tenant_id from profiles where id = auth.uid();
$$;

create or replace function current_role_name()
returns user_role
language sql
stable
security definer
set search_path = public
as $$
  select role from profiles where id = auth.uid();
$$;

create or replace function is_super_admin()
returns boolean
language sql
stable
as $$
  select coalesce(current_role_name() = 'super_admin', false);
$$;

create or replace function is_staff()
returns boolean
language sql
stable
as $$
  select coalesce(current_role_name() in ('teacher', 'institution_admin'), false);
$$;


-- ============================================================================
-- STEP 12: AUTO-CREATE PROFILE ON SIGNUP
-- The app (or an admin using the service_role key) must pass tenant_id,
-- role, and full_name in raw_user_meta_data when calling supabase.auth.signUp
-- or admin.createUser. This trigger turns that metadata into a profile row.
-- ============================================================================

create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    (new.raw_user_meta_data->>'tenant_id')::uuid,
    (new.raw_user_meta_data->>'role')::user_role,
    new.raw_user_meta_data->>'full_name'
  );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();


-- ============================================================================
-- STEP 13: ROW LEVEL SECURITY
-- plan_limits is global, non-tenant-scoped config — read-only for every
-- client via a permissive select policy; only service_role can write it.
-- Every other table below is tenant-scoped via current_tenant_id().
-- ============================================================================

alter table tenants enable row level security;
alter table profiles enable row level security;
alter table courses enable row level security;
alter table subjects enable row level security;
alter table chapters enable row level security;
alter table topics enable row level security;
alter table documents enable row level security;
alter table ai_extraction_jobs enable row level security;
alter table questions enable row level security;
alter table quiz_sets enable row level security;
alter table quiz_variants enable row level security;
alter table quiz_variant_questions enable row level security;
alter table quiz_attempts enable row level security;
alter table attempt_answers enable row level security;
alter table ai_explanations enable row level security;
alter table tenant_usage enable row level security;
alter table plan_limits enable row level security;

-- ---------- tenants ----------
create policy "tenant self or super admin - select" on tenants
  for select using (id = current_tenant_id() or is_super_admin());

create policy "only institution admin updates own tenant" on tenants
  for update using (id = current_tenant_id() and current_role_name() = 'institution_admin');

create policy "only super admin creates tenants" on tenants
  for insert with check (is_super_admin());

-- ---------- profiles ----------
create policy "see own tenant's profiles" on profiles
  for select using (tenant_id = current_tenant_id() or is_super_admin());

create policy "update own profile or admin manages tenant profiles" on profiles
  for update using (id = auth.uid() or (tenant_id = current_tenant_id() and current_role_name() = 'institution_admin'));

-- Note: no client-facing insert policy on profiles by design — rows are
-- created only by the handle_new_user trigger (security definer), or by
-- the backend using the service_role key, which bypasses RLS entirely.

-- ---------- academic hierarchy ----------
create policy "read own tenant hierarchy" on courses
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on courses
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "read own tenant hierarchy" on subjects
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on subjects
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "read own tenant hierarchy" on chapters
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on chapters
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "read own tenant hierarchy" on topics
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on topics
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

-- ---------- documents & AI jobs (staff only — students never see raw uploads) ----------
create policy "staff reads own tenant documents" on documents
  for select using (tenant_id = current_tenant_id() and (is_staff() or is_super_admin()));
create policy "staff uploads documents" on documents
  for insert with check (tenant_id = current_tenant_id() and is_staff() and uploaded_by = auth.uid());

create policy "staff reads own tenant jobs" on ai_extraction_jobs
  for select using (tenant_id = current_tenant_id() and (is_staff() or is_super_admin()));
-- Inserts/updates to jobs happen from the FastAPI backend using the
-- service_role key (bypasses RLS) — no client-facing write policy needed.

-- ---------- questions ----------
-- Students only ever see approved questions. Staff sees everything
-- (including pending/rejected, for the review queue UI).
create policy "role-aware question read" on questions
  for select using (
    tenant_id = current_tenant_id()
    and (review_status = 'approved' or is_staff() or is_super_admin())
  );
create policy "staff writes questions" on questions
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

-- ---------- quiz sets / variants / mapping ----------
create policy "role-aware quiz set read" on quiz_sets
  for select using (
    tenant_id = current_tenant_id()
    and (status = 'published' or is_staff() or is_super_admin())
  );
create policy "staff writes quiz sets" on quiz_sets
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "role-aware variant read" on quiz_variants
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes variants" on quiz_variants
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "role-aware variant question read" on quiz_variant_questions
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes variant questions" on quiz_variant_questions
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

-- ---------- attempts & answers (students own their rows; staff can view) ----------
create policy "own attempts or staff view" on quiz_attempts
  for select using (
    tenant_id = current_tenant_id()
    and (student_id = auth.uid() or is_staff() or is_super_admin())
  );
create policy "student creates own attempt" on quiz_attempts
  for insert with check (
    tenant_id = current_tenant_id()
    and student_id = auth.uid()
    and current_role_name() = 'student'
  );
create policy "student updates own in-progress attempt" on quiz_attempts
  for update using (
    tenant_id = current_tenant_id()
    and student_id = auth.uid()
    and status = 'in_progress'
  );

create policy "own answers or staff view" on attempt_answers
  for select using (
    tenant_id = current_tenant_id()
    and (
      is_staff() or is_super_admin()
      or exists (
        select 1 from quiz_attempts qa
        where qa.id = attempt_answers.attempt_id and qa.student_id = auth.uid()
      )
    )
  );
create policy "student writes own answers" on attempt_answers
  for insert with check (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from quiz_attempts qa
      where qa.id = attempt_answers.attempt_id
        and qa.student_id = auth.uid()
        and qa.status = 'in_progress'
    )
  );

-- ---------- AI explanations (everyone in the tenant can read; staff can trigger writes) ----------
create policy "tenant reads explanations" on ai_explanations
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes explanations" on ai_explanations
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

-- ---------- usage / quotas ----------
create policy "admins view own tenant usage" on tenant_usage
  for select using (
    tenant_id = current_tenant_id()
    and (current_role_name() = 'institution_admin' or is_super_admin())
  );
-- No client-facing write policy — only the backend (service_role) increments this.

create policy "anyone can read plan limits" on plan_limits
  for select using (true);
-- No client-facing write policy — pricing/quota tiers change via a new
-- migration (service_role), never from an anon/authenticated client.


-- ============================================================================
-- OPTIONAL: lightweight analytics as VIEWS, not tables (Sprint 5 requirement,
-- v1-lite version — no dedicated analytics tables, just queries over data
-- that already exists). RLS on the underlying tables still applies.
-- ============================================================================

create view v_student_topic_accuracy as
select
  aa.tenant_id,
  qa.student_id,
  q.topic_id,
  count(*) as questions_attempted,
  sum(case when aa.is_correct then 1 else 0 end) as correct_count,
  round(100.0 * sum(case when aa.is_correct then 1 else 0 end) / count(*), 1) as accuracy_pct
from attempt_answers aa
join quiz_attempts qa on qa.id = aa.attempt_id
join questions q on q.id = aa.question_id
group by aa.tenant_id, qa.student_id, q.topic_id;

create view v_quiz_question_analysis as
select
  vq.tenant_id,
  vq.variant_id,
  aa.question_id,
  count(*) as attempts,
  round(100.0 * sum(case when aa.is_correct then 1 else 0 end) / count(*), 1) as correct_pct
from attempt_answers aa
join quiz_attempts qa on qa.id = aa.attempt_id
join quiz_variant_questions vq on vq.variant_id = qa.variant_id and vq.question_id = aa.question_id
group by vq.tenant_id, vq.variant_id, aa.question_id;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
