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
create type document_status as enum ('uploaded', 'processing', 'completed', 'failed', 'archived');
create type job_status as enum ('queued', 'running', 'succeeded', 'failed');
create type variant_type as enum ('theory', 'practical', 'mixed');
create type quiz_status as enum ('draft', 'published', 'archived');
create type attempt_status as enum ('in_progress', 'submitted', 'graded', 'abandoned');
create type generation_job_status as enum ('queued', 'running', 'partial', 'completed', 'failed');


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
  logo_filename text check (logo_filename is null or char_length(logo_filename) <= 255),
  primary_color text not null default '#2E8857' check (primary_color ~ '^#[0-9A-Fa-f]{6}$'),
  feature_flags jsonb not null default '{"faculty_jobs":true,"quiz_reuse":true,"batches":true,"scoring_policies":true,"commerce_pack":true,"figure_attach":true}'::jsonb check (jsonb_typeof(feature_flags) = 'object'),
  handwritten_evaluation_enabled boolean not null default false,
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
  must_change_password boolean not null default false,
  created_at timestamptz not null default now()
);
create index idx_profiles_tenant on profiles(tenant_id);
create unique index uq_profiles_id_tenant on profiles(id, tenant_id);


-- ============================================================================
-- STEP 4: ACADEMIC HIERARCHY (Course -> Subject -> Chapter -> Topic)
-- ============================================================================

-- Global optional catalogue. Institutions may provision these reference rows
-- into the tenant-scoped operational courses/subjects below; free-form rows
-- remain valid by leaving their catalogue link null.
create table catalog_courses (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null,
  is_active boolean not null default true,
  display_order integer not null default 0
);

create table catalog_course_levels (
  id uuid primary key default gen_random_uuid(),
  catalog_course_id uuid not null references catalog_courses(id) on delete cascade,
  name text not null,
  is_active boolean not null default true,
  display_order integer not null default 0,
  unique (catalog_course_id, name)
);
create index idx_catalog_course_levels_course on catalog_course_levels(catalog_course_id);

create table catalog_course_subjects (
  id uuid primary key default gen_random_uuid(),
  catalog_level_id uuid not null references catalog_course_levels(id) on delete cascade,
  name text not null,
  is_active boolean not null default true,
  unique (catalog_level_id, name)
);
create index idx_catalog_course_subjects_level on catalog_course_subjects(catalog_level_id);

create table courses (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  name text not null,
  catalog_course_id uuid references catalog_courses(id) on delete set null,
  created_at timestamptz not null default now()
);
create index idx_courses_tenant on courses(tenant_id);
create index idx_courses_catalog_course on courses(catalog_course_id);
create unique index uq_courses_tenant_freeform_name on courses(tenant_id, name)
  where catalog_course_id is null;
create unique index uq_courses_tenant_catalog on courses(tenant_id, catalog_course_id)
  where catalog_course_id is not null;

create table course_levels (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  course_id uuid not null references courses(id) on delete cascade,
  name text not null,
  catalog_level_id uuid references catalog_course_levels(id) on delete set null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (id, tenant_id, course_id)
);
create unique index if not exists uq_course_levels_id_tenant_course
  on course_levels(id, tenant_id, course_id);
create index idx_course_levels_tenant_course on course_levels(tenant_id, course_id);
create unique index uq_course_levels_tenant_catalog
  on course_levels(tenant_id, catalog_level_id) where catalog_level_id is not null;
create unique index uq_course_levels_course_custom_name
  on course_levels(course_id, lower(name)) where catalog_level_id is null;

create table subjects (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  course_id uuid not null references courses(id) on delete cascade,
  course_level_id uuid not null,
  name text not null,
  catalog_subject_id uuid references catalog_course_subjects(id) on delete set null,
  constraint subjects_course_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references course_levels(id, tenant_id, course_id) on delete cascade
);
create index idx_subjects_tenant on subjects(tenant_id);
create index idx_subjects_course on subjects(course_id);
create index idx_subjects_tenant_course_level on subjects(tenant_id, course_id, course_level_id);
create index idx_subjects_catalog_subject on subjects(catalog_subject_id);
create unique index uq_subjects_id_tenant on subjects(id, tenant_id);
create unique index uq_subjects_tenant_course_freeform_name
  on subjects(tenant_id, course_id, name) where catalog_subject_id is null;
create unique index uq_subjects_tenant_catalog
  on subjects(tenant_id, catalog_subject_id) where catalog_subject_id is not null;

create table institution_offerings (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  catalog_subject_id uuid not null references catalog_course_subjects(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (tenant_id, catalog_subject_id)
);
create index idx_institution_offerings_tenant on institution_offerings(tenant_id);
create index idx_institution_offerings_subject on institution_offerings(catalog_subject_id);

-- A student is enrolled in courses. Teacher course rows are retained for
-- reporting compatibility and are derived from explicit subject assignments.
create table enrollments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  profile_id uuid not null references profiles(id) on delete cascade,
  course_id uuid not null references courses(id) on delete cascade,
  course_level_id uuid,
  created_at timestamptz not null default now(),
  unique (profile_id, course_id),
  constraint enrollments_course_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references course_levels(id, tenant_id, course_id) on delete restrict
);
create index idx_enrollments_tenant on enrollments(tenant_id);
create index idx_enrollments_profile on enrollments(profile_id);
create index idx_enrollments_course on enrollments(course_id);
create index idx_enrollments_student_level on enrollments(tenant_id, profile_id, course_level_id);

create table teacher_subjects (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  teacher_id uuid not null,
  subject_id uuid not null,
  created_at timestamptz not null default now(),
  constraint teacher_subjects_teacher_tenant_fk
    foreign key (teacher_id, tenant_id)
    references profiles(id, tenant_id) on delete cascade,
  constraint teacher_subjects_subject_tenant_fk
    foreign key (subject_id, tenant_id)
    references subjects(id, tenant_id) on delete cascade,
  unique (teacher_id, subject_id)
);
create index idx_teacher_subjects_tenant on teacher_subjects(tenant_id);
create index idx_teacher_subjects_teacher on teacher_subjects(teacher_id);
create index idx_teacher_subjects_subject on teacher_subjects(subject_id);

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
  uploaded_by uuid references profiles(id) on delete set null,
  chapter_id uuid references chapters(id),
  storage_path text not null,              -- path inside the Supabase Storage bucket
  original_filename text,
  file_type text,
  status document_status not null default 'uploaded',
  error_message text,
  created_at timestamptz not null default now()
);
create index idx_documents_tenant on documents(tenant_id);

-- Private source-document bucket. The per-bucket ceiling is 30 MiB, matching
-- both frontend and backend validation. The image MIME types are retained for
-- the separate Extract Quiz flow, which also stores its source in this bucket.
insert into storage.buckets (
  id,
  name,
  public,
  file_size_limit,
  allowed_mime_types
)
values (
  'documents',
  'documents',
  false,
  31457280,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/png',
    'image/jpeg'
  ]
)
on conflict (id) do update
set file_size_limit = excluded.file_size_limit;

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
  source_excerpt text,                      -- verbatim evidence for generated questions
  source_page_start integer,
  source_page_end integer,
  grounding_confidence numeric check (
    grounding_confidence is null or (grounding_confidence >= 0 and grounding_confidence <= 1)
  ),
  verification_status text not null default 'needs_teacher_review' check (
    verification_status in ('verified', 'needs_teacher_review', 'unsupported', 'ambiguous')
  ),
  verification_warnings jsonb not null default '[]'::jsonb check (
    jsonb_typeof(verification_warnings) = 'array'
  ),
  review_status review_status not null default 'pending_review',
  reviewed_by uuid references profiles(id) on delete set null,
  reviewed_at timestamptz,
  embedding vector(1536),                   -- for semantic duplicate detection
  created_by uuid references profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  constraint questions_source_page_range_check check (
    (source_page_start is null and source_page_end is null)
    or (
      source_page_start is not null and source_page_end is not null
      and source_page_start > 0 and source_page_end >= source_page_start
    )
  )
);
create index idx_questions_tenant on questions(tenant_id);
create index idx_questions_chapter on questions(chapter_id);
create index idx_questions_review_status on questions(review_status);
create index idx_questions_verification_status on questions(tenant_id, verification_status);
-- HNSW index for fast cosine-similarity search (duplicate detection)
create index idx_questions_embedding on questions using hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- STEP 7: QUIZ ENGINE (Quiz Set -> Variant -> Questions)
-- ============================================================================

create table quiz_sets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  chapter_id uuid references chapters(id),
  subject_id uuid references subjects(id),
  document_id uuid references documents(id) on delete set null,
  title text not null,
  description text,
  status quiz_status not null default 'draft',
  created_by uuid references profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  published_at timestamptz
);
create index idx_quizsets_tenant on quiz_sets(tenant_id);
create index idx_quizsets_subject on quiz_sets(subject_id);
create index idx_quizsets_tenant_document on quiz_sets(tenant_id, document_id);

-- Transient, resumable state for large-document Map-Reduce analysis.
create table document_chunks (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  document_id uuid not null references documents(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  content_hash text not null,
  char_start int,
  char_end int,
  page_start int,
  page_end int,
  topics_json jsonb,
  map_status job_status not null default 'queued',
  attempts int not null default 0,
  error_message text,
  updated_at timestamptz not null default now(),
  unique (document_id, chunk_index),
  unique (document_id, content_hash)
);
create index idx_docchunks_document on document_chunks(document_id);
create index idx_docchunks_tenant on document_chunks(tenant_id);
create index idx_docchunks_mapstatus on document_chunks(document_id, map_status);

create table quiz_generation_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id),
  created_by uuid not null references profiles(id) on delete cascade,
  document_id uuid not null references documents(id) on delete cascade,
  subject_id uuid references subjects(id),
  chapter_name text,
  params jsonb not null default '{}'::jsonb,
  master_blueprint jsonb,
  status generation_job_status not null default 'queued',
  phase text not null default 'queued',
  total_chunks int not null default 0,
  done_chunks int not null default 0,
  quiz_set_id uuid references quiz_sets(id) on delete set null,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_genjobs_tenant on quiz_generation_jobs(tenant_id);
create index idx_genjobs_document on quiz_generation_jobs(document_id);
create index idx_genjobs_status on quiz_generation_jobs(status);

-- Metadata-only provider telemetry. Prompts and responses are never stored.
create table api_call_logs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid references tenants(id) on delete set null,
  document_id uuid references documents(id) on delete set null,
  job_id uuid references quiz_generation_jobs(id) on delete set null,
  call_type text not null,
  provider text not null check (provider in ('gemini', 'deepseek')),
  model text not null,
  was_fallback boolean not null default false,
  input_tokens integer,
  output_tokens integer,
  cached_tokens integer,
  thinking_tokens integer,
  cost_usd numeric(18, 8),
  cost_inr numeric(18, 8),
  latency_ms integer not null,
  status text not null check (status in ('success', 'error')),
  error_message text,
  created_at timestamptz not null default now()
);
create index idx_api_call_logs_document on api_call_logs(document_id);
create index idx_api_call_logs_tenant_created on api_call_logs(tenant_id, created_at desc);
create index idx_api_call_logs_created on api_call_logs(created_at desc);
create index idx_api_call_logs_call_type on api_call_logs(call_type);

-- Migration 73: metadata-only quiz cost runs and complete filtered rollups.
-- Apply after migration 72; deploy API AND worker after applying.
create table if not exists public.ai_quiz_workflows (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  document_id uuid references public.documents(id) on delete set null,
  quiz_set_id uuid references public.quiz_sets(id) on delete set null,
  kind text not null check (kind in ('generation','extraction')),
  status text not null check (status in ('running','completed','failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
alter table public.ai_quiz_workflows enable row level security;
revoke all on public.ai_quiz_workflows from public,anon,authenticated;
grant select,insert,update,delete on public.ai_quiz_workflows to service_role;
create index if not exists ai_quiz_workflows_document on public.ai_quiz_workflows(document_id);
create index if not exists ai_quiz_workflows_quiz on public.ai_quiz_workflows(quiz_set_id);
create index if not exists ai_quiz_workflows_tenant_time on public.ai_quiz_workflows(tenant_id,started_at desc);
alter table public.api_call_logs add column if not exists workflow_id uuid
  references public.ai_quiz_workflows(id) on delete cascade;
create index if not exists api_call_logs_workflow_time on public.api_call_logs(workflow_id,created_at desc);

create or replace function public.ai_quiz_cost_page(
  p_page integer default 1, p_page_size integer default 20,
  p_tenant uuid default null, p_document uuid default null,
  p_provider text default null, p_status text default null,
  p_from timestamptz default null, p_to timestamptz default null,
  p_kind text default null
) returns jsonb language sql stable security invoker set search_path='' as $$
with filtered as (
 select l.*, w.kind as workflow_kind,w.quiz_set_id,q.title as quiz_title,w.status as workflow_status,
   case when l.workflow_id is not null then 'run:'||l.workflow_id::text
        when l.document_id is not null then 'legacy:'||l.tenant_id::text||':'||l.document_id::text
        else 'unlinked:'||coalesce(l.tenant_id::text,'platform')||':'||l.call_type end as group_key
 from public.api_call_logs l
 left join public.ai_quiz_workflows w on w.id=l.workflow_id and w.tenant_id=l.tenant_id
 left join public.quiz_sets q on q.id=w.quiz_set_id and q.tenant_id=l.tenant_id
 where (p_tenant is null or l.tenant_id=p_tenant)
   and (p_document is null or l.document_id=p_document)
   and (p_provider is null or l.provider=p_provider)
   and (p_status is null or l.status=p_status)
   and (p_from is null or l.created_at>=p_from)
   and (p_to is null or l.created_at<=p_to)
   and (p_kind is null or w.kind=p_kind or (p_kind='legacy' and l.workflow_id is null))
), stages as (
 select group_key,call_type,count(*) as calls,sum(cost_usd) as cost_usd
 from filtered group by group_key,call_type
), grouped as (
 select group_key,
   (array_agg(workflow_id))[1] as workflow_id,
   (array_agg(tenant_id))[1] as tenant_id,
   (array_agg(document_id))[1] as document_id,
   (array_agg(quiz_set_id))[1] as quiz_set_id,
   min(quiz_title) as quiz_title,
   coalesce(min(workflow_kind),case when bool_or(document_id is not null) then 'legacy' else 'unlinked' end) as kind,
   coalesce(min(workflow_status),'historical') as status,
   min(created_at) as started_at,max(created_at) as last_call_at,
   count(*) as call_count,count(*) filter(where status='error') as error_count,
   count(*) filter(where cost_usd is null) as unpriced_calls,
   sum(cost_usd) as cost_usd,sum(cost_inr) as cost_inr,
   coalesce(sum(input_tokens),0) as input_tokens,coalesce(sum(output_tokens),0) as output_tokens,
   coalesce(sum(thinking_tokens),0) as thinking_tokens,coalesce(sum(cached_tokens),0) as cached_tokens,
   sum(latency_ms) as provider_latency_ms
 from filtered group by group_key
), page_rows as (
 select g.*, (select jsonb_agg(jsonb_build_object('call_type',s.call_type,'calls',s.calls,'cost_usd',s.cost_usd)
    order by s.call_type) from stages s where s.group_key=g.group_key) as stages
 from grouped g order by last_call_at desc,group_key
 limit least(greatest(p_page_size,1),50)
 offset (greatest(p_page,1)-1)*least(greatest(p_page_size,1),50)
)
select jsonb_build_object(
 'items',coalesce((select jsonb_agg(to_jsonb(r) order by r.last_call_at desc,r.group_key) from page_rows r),'[]'::jsonb),
 'total',(select count(*) from grouped),
 'cost_usd',(select sum(cost_usd) from filtered),
 'call_count',(select count(*) from filtered),
 'unpriced_calls',(select count(*) from filtered where cost_usd is null)
);
$$;
revoke all on function public.ai_quiz_cost_page(integer,integer,uuid,uuid,text,text,timestamptz,timestamptz,text) from public,anon,authenticated;
grant execute on function public.ai_quiz_cost_page(integer,integer,uuid,uuid,text,text,timestamptz,timestamptz,text) to service_role;

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
  question_snapshot jsonb not null default '[]'::jsonb,
  started_at timestamptz not null default now(),
  submitted_at timestamptz,
  total_score numeric
);
create index idx_attempts_tenant on quiz_attempts(tenant_id);
create index idx_attempts_student on quiz_attempts(student_id);
create index idx_attempts_variant on quiz_attempts(variant_id);

-- The backend passes its configured maximum into this atomic creator. The
-- advisory lock serializes simultaneous starts for one student + variant.
create or replace function public.create_limited_quiz_attempt(
  p_tenant_id uuid,
  p_variant_id uuid,
  p_student_id uuid,
  p_started_at timestamptz,
  p_max_attempts integer,
  p_question_snapshot jsonb
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  created_id uuid;
begin
  if p_max_attempts < 1 then
    raise exception 'quiz_attempt_limit_invalid' using errcode = '22023';
  end if;
  if jsonb_typeof(p_question_snapshot) <> 'array'
     or jsonb_array_length(p_question_snapshot) < 1 then
    raise exception 'quiz_attempt_snapshot_invalid' using errcode = '22023';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      p_student_id::text || ':' || p_variant_id::text,
      0
    )
  );
  if (
    select count(*) >= p_max_attempts
    from public.quiz_attempts attempts
    where attempts.tenant_id = p_tenant_id
      and attempts.student_id = p_student_id
      and attempts.variant_id = p_variant_id
  ) then
    raise exception 'quiz_attempt_limit_reached' using errcode = '23514';
  end if;
  insert into public.quiz_attempts (
    tenant_id, variant_id, student_id, status, started_at, question_snapshot
  ) values (
    p_tenant_id, p_variant_id, p_student_id, 'in_progress', p_started_at,
    p_question_snapshot
  ) returning id into created_id;
  return created_id;
end;
$$;
revoke all on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb
) from public, anon, authenticated;
grant execute on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb
) to service_role;

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

-- Staff dashboard compound-filter indexes (migration-29).
create index idx_profiles_tenant_role on profiles(tenant_id, role);
create index idx_subjects_tenant_course on subjects(tenant_id, course_id);
create index idx_enrollments_tenant_course_profile on enrollments(tenant_id, course_id, profile_id);
create index idx_teacher_subjects_tenant_teacher_subject on teacher_subjects(tenant_id, teacher_id, subject_id);
create index idx_chapters_tenant_subject on chapters(tenant_id, subject_id);
create index idx_documents_tenant_uploader_created on documents(tenant_id, uploaded_by, created_at desc);
create index idx_questions_tenant_creator_chapter on questions(tenant_id, created_by, chapter_id);
create index idx_questions_tenant_review on questions(tenant_id, review_status);
create index idx_quizsets_tenant_creator_status on quiz_sets(tenant_id, created_by, status);
create index idx_quizsets_tenant_subject on quiz_sets(tenant_id, subject_id);
create index idx_variants_tenant_quizset on quiz_variants(tenant_id, quiz_set_id);
create index idx_vq_tenant_variant on quiz_variant_questions(tenant_id, variant_id);
create index idx_attempts_tenant_variant_status on quiz_attempts(tenant_id, variant_id, status);
create index idx_attempts_tenant_student_status_submitted on quiz_attempts(tenant_id, student_id, status, submitted_at desc);


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

-- One atomic rolling-hour counter per user and protected endpoint. The backend
-- accesses this only through consume_ai_rate_limit using the service role.
create table ai_rate_limits (
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid not null,
  endpoint text not null check (endpoint in (
    'quiz_generation',
    'blueprint_generation',
    'topic_extraction',
    'question_regenerate',
    'question_explain',
    'quiz_extraction',
    'challenge_join'
  )),
  window_started_at timestamptz not null,
  request_count integer not null check (request_count > 0),
  updated_at timestamptz not null default now(),
  primary key (tenant_id, user_id, endpoint),
  constraint ai_rate_limits_user_tenant_fk
    foreign key (user_id, tenant_id)
    references profiles(id, tenant_id) on delete cascade
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
-- Public metadata is untrusted. Every signup starts as a student; protected
-- backend provisioning may promote the profile using the service-role client.
-- ============================================================================

create or replace function handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  selected_tenant uuid;
  requested_course uuid;
  requested_level uuid;
  google_oauth_signup boolean;
begin
  -- Supabase Auth inserts user_metadata with auth.users, then applies custom
  -- app_metadata later. This routing hint only skips trigger provisioning;
  -- the protected backend still creates the authoritative profile.
  if coalesce(
    new.raw_user_meta_data->>'_backend_provisioning_intent', 'false'
  ) = 'true' or coalesce(
    new.raw_app_meta_data->>'provisioned_by_backend', 'false'
  ) = 'true' then
    return new;
  end if;

  requested_course := nullif(new.raw_user_meta_data->>'course_id', '')::uuid;
  requested_level := nullif(new.raw_user_meta_data->>'course_level_id', '')::uuid;
  google_oauth_signup :=
    coalesce(new.raw_app_meta_data->>'provider', '') = 'google'
    or (coalesce(new.raw_app_meta_data->'providers', '[]'::jsonb) ? 'google');

  if requested_course is null or requested_level is null then
    if google_oauth_signup then
      return new;
    end if;
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

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    new.id,
    selected_tenant,
    'student'::user_role,
    new.raw_user_meta_data->>'full_name'
  );

  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, new.id, requested_course, requested_level)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;

  return new;
end;
$$;

alter function public.handle_new_user() owner to postgres;
revoke all on function public.handle_new_user() from public, anon, authenticated, service_role;
grant execute on function public.handle_new_user() to supabase_auth_admin;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function handle_new_user();

-- A brand-new Google identity has no course metadata when auth.users is
-- inserted. The authenticated callback calls this function after course
-- selection. It derives the tenant from the course and can only create a
-- student profile; existing profiles are returned unchanged.
create or replace function complete_google_signup(
  p_course_id uuid,
  p_course_level_id uuid
)
returns table (
  out_tenant_id uuid,
  out_role public.user_role,
  out_course_id uuid,
  out_course_level_id uuid
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
  if current_user_id is null then
    raise exception 'Authentication is required';
  end if;

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

  select p.tenant_id, p.role
  into existing_tenant, existing_role
  from public.profiles p
  where p.id = current_user_id;

  if found then
    return query select existing_tenant, existing_role, null::uuid, null::uuid;
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

  insert into public.profiles (id, tenant_id, role, full_name)
  values (
    current_user_id,
    selected_tenant,
    'student'::public.user_role,
    nullif(trim(coalesce(user_metadata->>'full_name', user_metadata->>'name')), '')
  );

  insert into public.enrollments (tenant_id, profile_id, course_id, course_level_id)
  values (selected_tenant, current_user_id, p_course_id, p_course_level_id)
  on conflict (profile_id, course_id)
  do update set course_level_id = excluded.course_level_id;

  return query
    select selected_tenant, 'student'::public.user_role,
      p_course_id, p_course_level_id;
end;
$$;

revoke all on function complete_google_signup(uuid, uuid) from public, anon;
grant execute on function complete_google_signup(uuid, uuid) to authenticated;

-- Called only by the backend service role after an institution admin has been
-- authenticated. One transaction replaces assignments and their derived
-- teacher course-enrolment rows.
create or replace function replace_teacher_subjects(
  p_tenant_id uuid,
  p_teacher_id uuid,
  p_subject_ids uuid[] default '{}'::uuid[]
)
returns uuid[]
language plpgsql
security invoker
set search_path = ''
as $$
declare
  normalized_ids uuid[];
begin
  select coalesce(array_agg(subject_id order by first_position), '{}'::uuid[])
  into normalized_ids
  from (
    select subject_id, min(position) as first_position
    from unnest(coalesce(p_subject_ids, '{}'::uuid[]))
      with ordinality as requested(subject_id, position)
    group by subject_id
  ) deduplicated;

  if cardinality(normalized_ids) > 500 then
    raise exception 'A teacher may have at most 500 assigned subjects';
  end if;
  if not exists (
    select 1 from public.profiles
    where id = p_teacher_id and tenant_id = p_tenant_id and role = 'teacher'
  ) then
    raise exception 'Teacher not found in this institution';
  end if;
  if exists (
    select 1
    from unnest(normalized_ids) requested(subject_id)
    left join public.subjects s
      on s.id = requested.subject_id and s.tenant_id = p_tenant_id
    where s.id is null
  ) then
    raise exception 'One or more subjects do not belong to this institution';
  end if;

  delete from public.teacher_subjects
  where teacher_id = p_teacher_id and tenant_id = p_tenant_id;
  insert into public.teacher_subjects (tenant_id, teacher_id, subject_id)
  select p_tenant_id, p_teacher_id, subject_id
  from unnest(normalized_ids) requested(subject_id);

  delete from public.enrollments
  where profile_id = p_teacher_id and tenant_id = p_tenant_id;
  insert into public.enrollments (tenant_id, profile_id, course_id)
  select distinct p_tenant_id, p_teacher_id, s.course_id
  from public.subjects s
  where s.tenant_id = p_tenant_id and s.id = any(normalized_ids)
  on conflict (profile_id, course_id) do nothing;

  return normalized_ids;
end;
$$;

revoke all on function replace_teacher_subjects(uuid, uuid, uuid[])
  from public, anon, authenticated;
grant execute on function replace_teacher_subjects(uuid, uuid, uuid[])
  to service_role;

-- Atomically materializes one active catalogue subject into a tenant's
-- operational course/subject hierarchy. It is callable only by service_role;
-- FastAPI performs the verified role and tenant checks before invoking it.
create or replace function provision_catalog_subject(
  p_tenant_id uuid,
  p_catalog_subject_id uuid
)
returns table (
  course_id uuid,
  subject_id uuid,
  course_name_collision boolean,
  subject_name_collision boolean
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  catalog_course public.catalog_courses%rowtype;
  catalog_level public.catalog_course_levels%rowtype;
  catalog_subject public.catalog_course_subjects%rowtype;
  resolved_course_id uuid;
  resolved_level_id uuid;
  resolved_subject_id uuid;
  has_course_collision boolean;
  has_subject_collision boolean;
begin
  if not exists (select 1 from public.tenants where id = p_tenant_id) then
    raise exception 'Tenant not found';
  end if;

  select cc.* into catalog_course
  from public.catalog_course_subjects cs
  join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
  join public.catalog_courses cc on cc.id = cl.catalog_course_id
  where cs.id = p_catalog_subject_id
    and cs.is_active = true and cl.is_active = true and cc.is_active = true;
  if not found then raise exception 'Active catalog subject not found'; end if;

  select cl.* into catalog_level
  from public.catalog_course_subjects cs
  join public.catalog_course_levels cl on cl.id = cs.catalog_level_id
  where cs.id = p_catalog_subject_id;
  select cs.* into catalog_subject
  from public.catalog_course_subjects cs
  where cs.id = p_catalog_subject_id;

  select exists (
    select 1 from public.courses c
    where c.tenant_id = p_tenant_id and c.name = catalog_course.name
      and c.catalog_course_id is null
  ) into has_course_collision;

  insert into public.courses (tenant_id, name, catalog_course_id)
  values (p_tenant_id, catalog_course.name, catalog_course.id)
  on conflict (tenant_id, catalog_course_id) where catalog_course_id is not null
  do update set catalog_course_id = excluded.catalog_course_id
  returning id into resolved_course_id;

  insert into public.course_levels (tenant_id, course_id, name, catalog_level_id)
  values (p_tenant_id, resolved_course_id, catalog_level.name, catalog_level.id)
  on conflict (tenant_id, catalog_level_id) where catalog_level_id is not null
  do update set course_id = excluded.course_id, name = excluded.name, is_active = true
  returning id into resolved_level_id;

  select exists (
    select 1 from public.subjects s
    where s.tenant_id = p_tenant_id and s.course_id = resolved_course_id
      and s.name = catalog_subject.name and s.catalog_subject_id is null
  ) into has_subject_collision;

  insert into public.subjects (tenant_id, course_id, course_level_id, name, catalog_subject_id)
  values (p_tenant_id, resolved_course_id, resolved_level_id, catalog_subject.name, catalog_subject.id)
  on conflict (tenant_id, catalog_subject_id) where catalog_subject_id is not null
  do update set course_id = excluded.course_id,
    course_level_id = excluded.course_level_id,
    name = excluded.name,
    catalog_subject_id = excluded.catalog_subject_id
  returning id into resolved_subject_id;

  insert into public.institution_offerings (tenant_id, catalog_subject_id)
  values (p_tenant_id, catalog_subject.id)
  on conflict (tenant_id, catalog_subject_id) do nothing;

  if has_course_collision or has_subject_collision then
    raise log 'Catalog provisioning kept same-name free-form rows separate (tenant %, catalog subject %, course collision %, subject collision %)',
      p_tenant_id, p_catalog_subject_id, has_course_collision, has_subject_collision;
  end if;

  return query select resolved_course_id, resolved_subject_id,
    has_course_collision, has_subject_collision;
end;
$$;

revoke all on function provision_catalog_subject(uuid, uuid)
  from public, anon, authenticated;
grant execute on function provision_catalog_subject(uuid, uuid) to service_role;

-- Atomically consumes one request from a user's rolling one-hour quota.
-- The upsert locks the counter row, so concurrent Railway workers cannot
-- both pass after only one remaining request.
create or replace function consume_ai_rate_limit(
  p_tenant_id uuid,
  p_user_id uuid,
  p_endpoint text,
  p_limit integer
)
returns table (
  allowed boolean,
  retry_after_seconds integer,
  remaining integer
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  request_time timestamptz := clock_timestamp();
  consumed_count integer;
  active_window_start timestamptz;
begin
  if p_limit < 1 then
    raise exception 'Rate limit must be a positive integer';
  end if;
  if p_endpoint not in (
    'quiz_generation',
    'blueprint_generation',
    'topic_extraction',
    'question_regenerate',
    'question_explain',
    'quiz_extraction',
    'challenge_join'
  ) then
    raise exception 'Unknown rate-limit endpoint';
  end if;

  insert into public.ai_rate_limits as limits (
    tenant_id, user_id, endpoint, window_started_at, request_count, updated_at
  )
  values (p_tenant_id, p_user_id, p_endpoint, request_time, 1, request_time)
  on conflict (tenant_id, user_id, endpoint) do update
  set
    window_started_at = case
      when limits.window_started_at <= request_time - interval '1 hour'
        then request_time
      else limits.window_started_at
    end,
    request_count = case
      when limits.window_started_at <= request_time - interval '1 hour'
        then 1
      else limits.request_count + 1
    end,
    updated_at = request_time
  where
    limits.window_started_at <= request_time - interval '1 hour'
    or limits.request_count < p_limit
  returning limits.request_count, limits.window_started_at
  into consumed_count, active_window_start;

  if found then
    return query select true, 0, greatest(p_limit - consumed_count, 0);
    return;
  end if;

  select limits.window_started_at
  into active_window_start
  from public.ai_rate_limits as limits
  where limits.tenant_id = p_tenant_id
    and limits.user_id = p_user_id
    and limits.endpoint = p_endpoint;

  return query
  select
    false,
    greatest(
      1,
      ceil(extract(epoch from (
        active_window_start + interval '1 hour' - request_time
      )))::integer
    ),
    0;
end;
$$;

revoke all on function consume_ai_rate_limit(uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function consume_ai_rate_limit(uuid, uuid, text, integer)
  to service_role;


-- ============================================================================
-- STEP 13: ROW LEVEL SECURITY
-- plan_limits and the three catalog_* tables are global reference data.
-- The catalogue is authenticated-read with super-admin-only writes;
-- plan_limits is read-only for every client. All operational tables remain
-- tenant-scoped via current_tenant_id().
-- ============================================================================

alter table tenants enable row level security;
alter table profiles enable row level security;
alter table catalog_courses enable row level security;
alter table catalog_course_levels enable row level security;
alter table catalog_course_subjects enable row level security;
alter table courses enable row level security;
alter table course_levels enable row level security;
alter table subjects enable row level security;
alter table institution_offerings enable row level security;
alter table enrollments enable row level security;
alter table teacher_subjects enable row level security;
alter table chapters enable row level security;
alter table topics enable row level security;
alter table documents enable row level security;
alter table ai_extraction_jobs enable row level security;
alter table document_chunks enable row level security;
alter table quiz_generation_jobs enable row level security;
alter table api_call_logs enable row level security;
alter table questions enable row level security;
alter table quiz_sets enable row level security;
alter table quiz_variants enable row level security;
alter table quiz_variant_questions enable row level security;
alter table quiz_attempts enable row level security;
alter table attempt_answers enable row level security;
alter table ai_explanations enable row level security;
alter table tenant_usage enable row level security;
alter table plan_limits enable row level security;
alter table ai_rate_limits enable row level security;

revoke all on table ai_rate_limits from public, anon, authenticated;
grant select, insert, update, delete on table ai_rate_limits to service_role;
grant select, insert, update, delete on table document_chunks to service_role;
grant select, insert, update, delete on table quiz_generation_jobs to service_role;
revoke all on table api_call_logs from public, anon, authenticated;
grant select, insert, update, delete on table api_call_logs to service_role;
revoke all on table catalog_courses, catalog_course_levels, catalog_course_subjects
  from public, anon, authenticated;
grant select, insert, update, delete on table
  catalog_courses, catalog_course_levels, catalog_course_subjects
  to authenticated;
grant select, insert, update, delete on table
  catalog_courses, catalog_course_levels, catalog_course_subjects
  to service_role;
revoke all on table course_levels from public, anon, authenticated;
grant select, insert, update, delete on table course_levels to service_role;
revoke all on table institution_offerings from public, anon, authenticated;
grant select, insert, delete on table institution_offerings to authenticated;
grant select, insert, update, delete on table institution_offerings to service_role;

-- ---------- tenants ----------
create policy "tenant self or super admin - select" on tenants
  for select using (id = current_tenant_id() or is_super_admin());

create policy "only institution admin updates own tenant" on tenants
  for update using (id = current_tenant_id() and current_role_name() = 'institution_admin');

create policy "only super admin creates tenants" on tenants
  for insert with check (is_super_admin());

-- ---------- profiles ----------
create policy "read own profile" on profiles
  for select to authenticated using (id = auth.uid());

create policy "update own safe profile fields" on profiles
  for update using (id = auth.uid())
  with check (
    id = auth.uid()
    and tenant_id = current_tenant_id()
    and role = current_role_name()
  );

revoke update on table profiles from authenticated;
grant update (full_name, avatar_url) on table profiles to authenticated;

-- Note: no client-facing insert policy on profiles by design — rows are
-- created only by the handle_new_user trigger (security definer), or by
-- the backend using the service_role key, which bypasses RLS entirely.

-- ---------- academic hierarchy ----------
create policy "authenticated read catalog courses" on catalog_courses
  for select to authenticated using (true);
create policy "authenticated read catalog levels" on catalog_course_levels
  for select to authenticated using (true);
create policy "authenticated read catalog subjects" on catalog_course_subjects
  for select to authenticated using (true);

create policy "super admins insert catalog courses" on catalog_courses
  for insert to authenticated with check ((select is_super_admin()));
create policy "super admins update catalog courses" on catalog_courses
  for update to authenticated using ((select is_super_admin()))
  with check ((select is_super_admin()));
create policy "super admins delete catalog courses" on catalog_courses
  for delete to authenticated using ((select is_super_admin()));
create policy "super admins insert catalog levels" on catalog_course_levels
  for insert to authenticated with check ((select is_super_admin()));
create policy "super admins update catalog levels" on catalog_course_levels
  for update to authenticated using ((select is_super_admin()))
  with check ((select is_super_admin()));
create policy "super admins delete catalog levels" on catalog_course_levels
  for delete to authenticated using ((select is_super_admin()));
create policy "super admins insert catalog subjects" on catalog_course_subjects
  for insert to authenticated with check ((select is_super_admin()));
create policy "super admins update catalog subjects" on catalog_course_subjects
  for update to authenticated using ((select is_super_admin()))
  with check ((select is_super_admin()));
create policy "super admins delete catalog subjects" on catalog_course_subjects
  for delete to authenticated using ((select is_super_admin()));

create policy "tenant members read institution offerings" on institution_offerings
  for select to authenticated using (
    tenant_id = (select current_tenant_id()) or (select is_super_admin())
  );
create policy "institution admins insert own offerings" on institution_offerings
  for insert to authenticated with check (
    (tenant_id = (select current_tenant_id())
      and (select current_role_name()) = 'institution_admin')
    or (select is_super_admin())
  );
create policy "institution admins delete own offerings" on institution_offerings
  for delete to authenticated using (
    (tenant_id = (select current_tenant_id())
      and (select current_role_name()) = 'institution_admin')
    or (select is_super_admin())
  );

create policy "read own tenant hierarchy" on courses
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on courses
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "read own tenant course levels" on course_levels
  for select to authenticated using (
    tenant_id = (select current_tenant_id()) or (select is_super_admin())
  );
create policy "institution admins manage course levels" on course_levels
  for all to authenticated
  using (
    tenant_id = (select current_tenant_id())
    and (select current_role_name()) = 'institution_admin'
  )
  with check (
    tenant_id = (select current_tenant_id())
    and (select current_role_name()) = 'institution_admin'
  );

create policy "read own tenant hierarchy" on subjects
  for select using (tenant_id = current_tenant_id() or is_super_admin());
create policy "staff writes hierarchy" on subjects
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

create policy "read own enrollment or staff" on enrollments
  for select using (
    tenant_id = current_tenant_id()
    and (profile_id = auth.uid() or is_staff())
  );
create policy "institution admins manage enrollments" on enrollments
  for all using (
    tenant_id = current_tenant_id()
    and current_role_name() = 'institution_admin'
  )
  with check (
    tenant_id = current_tenant_id()
    and current_role_name() = 'institution_admin'
  );

create policy "read permitted teacher subjects" on teacher_subjects
  for select to authenticated
  using (
    is_super_admin()
    or (
      tenant_id = current_tenant_id()
      and (
        teacher_id = auth.uid()
        or current_role_name() = 'institution_admin'
      )
    )
  );

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

create policy "staff reads own tenant document chunks" on document_chunks
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

create policy "staff reads own tenant generation jobs" on quiz_generation_jobs
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

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

-- ---------- browser Data API boundary ----------
-- The frontend talks directly to Supabase only for Auth, its own profile row,
-- and complete_google_signup(). Quiz/content access goes through FastAPI so
-- students cannot bypass answer stripping by querying PostgREST themselves.
revoke all on table profiles from anon, authenticated;
grant select on table profiles to authenticated;
grant update (full_name, avatar_url) on table profiles to authenticated;

revoke all on table
  tenants, courses, course_levels, subjects, enrollments, teacher_subjects, chapters, topics,
  institution_offerings,
  documents, ai_extraction_jobs, questions, quiz_sets, quiz_variants,
  document_chunks, quiz_generation_jobs,
  quiz_variant_questions, quiz_attempts, attempt_answers, ai_explanations,
  tenant_usage, plan_limits, ai_rate_limits
from anon, authenticated;

-- The catalogue is the deliberate exception to the browser-table revoke above:
-- authenticated dashboards may read it, but mutations stay RLS-restricted.
grant select, insert, update, delete on table
  catalog_courses, catalog_course_levels, catalog_course_subjects
  to authenticated;
grant select, insert, delete on table institution_offerings to authenticated;

alter default privileges in schema public
  revoke all on tables from anon, authenticated;

revoke all on function complete_google_signup(uuid, uuid) from public, anon;
grant execute on function complete_google_signup(uuid, uuid) to authenticated;


-- ============================================================================
-- OPTIONAL: lightweight analytics as VIEWS, not tables (Sprint 5 requirement,
-- v1-lite version — no dedicated analytics tables, just queries over data
-- that already exists). RLS on the underlying tables still applies.
-- ============================================================================

create view v_student_topic_accuracy with (security_invoker = true) as
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

create view v_quiz_question_analysis with (security_invoker = true) as
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

-- Analytics are exposed through the tenant-scoped backend, not PostgREST.
revoke all on table
  v_student_topic_accuracy,
  v_quiz_question_analysis
from anon, authenticated;

-- ============================================================================
-- END OF ORIGINAL V1 BASELINE (integrated feature DDL follows)
-- ============================================================================

-- ============================================================================
-- INTEGRATED FEATURES ADDED AFTER THE ORIGINAL V1 BASELINE
-- Kept identical to migrations 49-56 so this file remains a complete fresh
-- install while existing databases can apply the numbered files in order.
-- ============================================================================
-- Migration 49 — Document figures (Phase 1 of document-figure support)
-- Apply after migration 48. Additive and safe; no existing row is changed.
-- Feature rollout is controlled by FIGURE_ATTACH_ENABLED at deployment level.
begin;

create unique index if not exists uq_documents_id_tenant
  on public.documents(id, tenant_id);

-- Private bucket for extracted figure PNGs. Served ONLY via short-lived signed
-- URLs minted by the trusted backend — never public. 5 MiB/PNG ceiling.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('question-figures', 'question-figures', false, 5242880, array['image/png'])
on conflict (id) do nothing;

-- One row per CAPTIONED figure extracted from a source document. The catalog the
-- (later) text-only generator reads to reference a real figure by id. Deleting
-- the source document cascades its figures.
create table if not exists public.document_figures (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id) on delete cascade,
  document_id   uuid not null,
  page          int,                    -- 1-based source page
  bbox          jsonb,                  -- {x0,y0,x1,y1} in PDF points (provenance)
  label         text,                   -- e.g. "Figure 8.1" / "Fig 3.4"
  caption       text,                   -- full caption text
  nearby_text   text,                   -- textual description for the catalog
  storage_path  text not null,          -- question-figures/{tenant}/{document}/{id}.png
  width         int,
  height        int,
  created_at    timestamptz not null default now(),
  constraint document_figures_document_tenant_fk
    foreign key (document_id, tenant_id)
    references public.documents(id, tenant_id) on delete cascade,
  unique (id, tenant_id)
);
create unique index if not exists uq_document_figures_id_tenant
  on public.document_figures(id, tenant_id);
create index if not exists idx_docfig_document on public.document_figures(document_id);
create index if not exists idx_docfig_tenant   on public.document_figures(tenant_id);

alter table public.document_figures enable row level security;
revoke all on public.document_figures from public, anon, authenticated;
grant select, insert, update, delete on public.document_figures to service_role;

-- Staff read only their own tenant's figures. All writes happen from the trusted
-- backend using the service_role key (which bypasses RLS), so there is no
-- client-facing write policy — same model as ai_extraction_jobs / faculty_jobs.
drop policy if exists "staff read own tenant figures" on public.document_figures;
create policy "staff read own tenant figures" on public.document_figures
  for select using (tenant_id = current_tenant_id() and is_staff());

commit;
-- Migration 50 — link a generated question to a source-document figure (Phase 2).
--
-- Additive + nullable. A question MAY carry one figure extracted from its source
-- document (see migration-49). Deleting the figure only clears the link via
-- ON DELETE SET NULL — it never deletes the question. Attachment is gated in app
-- code by FIGURE_ATTACH_ENABLED, is best-effort (never blocks generation), and is
-- confirmed/adjusted by the teacher in the review queue.
begin;

alter table public.questions add column if not exists figure_id uuid;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'questions_figure_tenant_fk'
      and conrelid = 'public.questions'::regclass
  ) then
    alter table public.questions
      add constraint questions_figure_tenant_fk
      foreign key (figure_id, tenant_id)
      references public.document_figures(id, tenant_id) on delete set null (figure_id);
  end if;
end $$;

-- Partial index: only linked questions are worth indexing (most carry no figure).
create index if not exists idx_questions_figure_id
  on public.questions(figure_id) where figure_id is not null;

commit;

notify pgrst, 'reload schema';
-- Migration 51 — immutable publication and safe quiz reuse.
-- Apply after migration 50.
-- Additive, rerunnable, service-only RPCs. No question/attempt data is deleted.
begin;
alter table public.questions add column if not exists content_version bigint not null default 1;
alter table public.questions add column if not exists release_locked boolean not null default false;
alter table public.questions add column if not exists origin_question_id uuid references public.questions(id) on delete set null;
alter table public.questions add column if not exists source_quiz_id uuid references public.quiz_sets(id) on delete set null;
alter table public.quiz_sets add column if not exists released_at timestamptz;
alter table public.quiz_sets add column if not exists last_publication_token text;
create index if not exists questions_origin_idx on public.questions(origin_question_id) where origin_question_id is not null;
create index if not exists questions_source_quiz_idx on public.questions(source_quiz_id) where source_quiz_id is not null;
create unique index if not exists uq_quiz_sets_id_tenant
  on public.quiz_sets(id, tenant_id);

create table if not exists public.quiz_copy_requests (
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 actor_id uuid not null,
 request_key uuid not null,
 source_id uuid not null,
 title text not null,
 quiz_id uuid not null,
 primary key(tenant_id,actor_id,request_key),
 constraint quiz_copy_requests_actor_tenant_fk
  foreign key (actor_id, tenant_id) references public.profiles(id, tenant_id) on delete cascade,
 constraint quiz_copy_requests_source_tenant_fk
  foreign key (source_id, tenant_id) references public.quiz_sets(id, tenant_id),
 constraint quiz_copy_requests_quiz_tenant_fk
  foreign key (quiz_id, tenant_id) references public.quiz_sets(id, tenant_id)
);
create index if not exists quiz_copy_requests_actor_idx on public.quiz_copy_requests(actor_id);
create index if not exists quiz_copy_requests_quiz_idx on public.quiz_copy_requests(quiz_id);
alter table public.quiz_copy_requests enable row level security;
revoke all on public.quiz_copy_requests from public,anon,authenticated;
grant select,insert on public.quiz_copy_requests to service_role;

-- Existing quizzes remain behaviour-neutral while QUIZ_REUSE_ENABLED is off.
-- The atomic publish RPC below sets released_at and release_locked together for
-- quizzes published through the new workflow; no historical row is backfilled.

create or replace function public.guard_released_question() returns trigger
language plpgsql set search_path=public as $$
#variable_conflict use_column
begin
 if tg_op='DELETE' then
  if old.release_locked then raise exception 'quiz_locked' using errcode='PT409'; end if;
  return old;
 end if;
 -- Author/reviewer anonymization and lineage FK cleanup remain permitted.
 if old.release_locked and ((to_jsonb(new)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])
   is distinct from (to_jsonb(old)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])) then
  raise exception 'quiz_locked' using errcode='PT409';
 end if;
 new.content_version:=old.content_version+1;
 return new;
end $$;
drop trigger if exists guard_released_question on public.questions;
create trigger guard_released_question before update or delete on public.questions
 for each row execute function public.guard_released_question();

create or replace function public.guard_released_structure() returns trigger
language plpgsql set search_path=public as $$
#variable_conflict use_column
declare ids uuid[]; s record;
begin
 if tg_table_name='quiz_variants' then
  ids:=array[case when tg_op<>'INSERT' then old.quiz_set_id end,case when tg_op<>'DELETE' then new.quiz_set_id end];
 else
  select array_agg(quiz_set_id) into ids from public.quiz_variants
   where id in (case when tg_op<>'INSERT' then old.variant_id end,case when tg_op<>'DELETE' then new.variant_id end);
 end if;
 -- Lock parents also for drafts: membership cannot change during release/copy.
 for s in select id,released_at from public.quiz_sets where id=any(ids) order by id for update loop
  if s.released_at is not null then raise exception 'quiz_locked' using errcode='PT409'; end if;
 end loop;
 if tg_op='DELETE' then return old; end if;
 return new;
end $$;
drop trigger if exists guard_released_variant on public.quiz_variants;
create trigger guard_released_variant before insert or update or delete on public.quiz_variants
 for each row execute function public.guard_released_structure();
drop trigger if exists guard_released_membership on public.quiz_variant_questions;
create trigger guard_released_membership before insert or update or delete on public.quiz_variant_questions
 for each row execute function public.guard_released_structure();

create or replace function public.assert_quiz_owner(p_id uuid,p_tenant uuid,p_actor uuid) returns void
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
begin
 if not exists(select 1 from public.quiz_sets s join public.profiles p on p.id=s.created_by
  join public.tenants t on t.id=s.tenant_id
  where s.id=p_id and s.tenant_id=p_tenant and s.created_by=p_actor
   and p.tenant_id=p_tenant and p.role='teacher' and t.is_active
   and (s.subject_id is null or exists(select 1 from public.teacher_subjects ts
    where ts.subject_id=s.subject_id and ts.teacher_id=p_actor and ts.tenant_id=p_tenant))) then
  raise exception 'quiz_no_access' using errcode='PT404';
 end if;
end $$;

create or replace function public.quiz_publication_state(p_id uuid,p_tenant uuid,p_actor uuid) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare token text; locked boolean;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select md5(jsonb_build_object('subject',s.subject_id,'document',s.document_id,'status',s.status,
  'variants',coalesce((select jsonb_agg(jsonb_build_array(v.id,v.variant_type,v.time_limit_minutes) order by v.id)
    from public.quiz_variants v where v.quiz_set_id=s.id),'[]'),
  'items',coalesce((select jsonb_agg(jsonb_build_array(l.id,l.variant_id,l.question_id,l.order_index,l.marks_override,q.content_version) order by l.id)
    from public.quiz_variants v join public.quiz_variant_questions l on l.variant_id=v.id
    join public.questions q on q.id=l.question_id where v.quiz_set_id=s.id),'[]'))::text),s.released_at is not null
 into token,locked from public.quiz_sets s where s.id=p_id;
 return jsonb_build_object('publication_token',token,'release_locked',locked,'reuse_enabled',true);
end $$;

create or replace function public.publish_quiz_atomic(p_id uuid,p_tenant uuid,p_actor uuid,p_token text) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; v record; n integer; total numeric;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 perform 1 from public.questions q where q.id in(select l.question_id from public.quiz_variant_questions l
  join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id) order by q.id for update;
 if s.status='published' and p_token is not null and s.last_publication_token=p_token then return to_jsonb(s); end if;
 if p_token is null or p_token is distinct from (public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token') then
  raise exception 'quiz_changed' using errcode='PT409';
 end if;
 if s.status='archived' then raise exception 'quiz_restore_first' using errcode='PT409'; end if;
 if s.status='published' then return to_jsonb(s); end if;
 if not exists(select 1 from public.quiz_variants where quiz_set_id=p_id) then
  raise exception 'quiz_empty' using errcode='PT409'; end if;
 for v in select * from public.quiz_variants where quiz_set_id=p_id order by id loop
  if v.tenant_id<>p_tenant or exists(select 1 from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and (l.tenant_id<>p_tenant or q.tenant_id<>p_tenant or q.created_by is distinct from p_actor
   or q.review_status not in ('approved','rejected'))) then raise exception 'quiz_review_required' using errcode='PT409'; end if;
  select count(*),sum(coalesce(l.marks_override,q.marks)) into n,total
   from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and q.review_status='approved';
  if n=0 or total is null or exists(select 1 from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and q.review_status='approved' and coalesce(l.marks_override,q.marks)<=0) then
   raise exception 'quiz_empty' using errcode='PT409'; end if;
  if s.released_at is null then update public.quiz_variants set total_marks=total where id=v.id; end if;
 end loop;
 update public.questions set release_locked=true where not release_locked and id in(
  select l.question_id from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id);
 update public.quiz_sets set status='published',published_at=now(),released_at=coalesce(released_at,now()),last_publication_token=p_token where id=p_id returning * into s;
 insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id)
  values(p_tenant,p_actor,'teacher','quiz.published','quiz_set',p_id);
 return to_jsonb(s);
end $$;

create or replace function public.copy_quiz_draft(p_id uuid,p_tenant uuid,p_actor uuid,p_key uuid,p_title text) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; prior public.quiz_copy_requests; dest uuid:=gen_random_uuid(); nv uuid; nq uuid;
 v record; l record; q public.questions; count_items integer; payload jsonb;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 if p_key is null or length(trim(p_title)) not between 1 and 200 then raise exception 'quiz_invalid_title' using errcode='PT400'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_tenant::text||p_actor::text||p_key::text,47));
 select * into prior from public.quiz_copy_requests where tenant_id=p_tenant and actor_id=p_actor and request_key=p_key;
 if found then
  if prior.source_id<>p_id or prior.title<>p_title then raise exception 'quiz_request_conflict' using errcode='PT409'; end if;
  return jsonb_build_object('quiz_set_id',prior.quiz_id,'replayed',true);
 end if;
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 perform 1 from public.questions q where q.id in(select l.question_id from public.quiz_variant_questions l
  join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id) order by q.id for update;
 select count(*) into count_items from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id;
 if count_items not between 1 and 500 then raise exception 'quiz_copy_size' using errcode='PT400'; end if;
 insert into public.quiz_sets(id,tenant_id,chapter_id,subject_id,document_id,title,description,status,created_by)
  values(dest,p_tenant,s.chapter_id,s.subject_id,s.document_id,p_title,s.description,'draft',p_actor);
 for v in select * from public.quiz_variants where quiz_set_id=p_id order by created_at,id loop
  if v.tenant_id<>p_tenant then raise exception 'quiz_no_access' using errcode='PT404'; end if;
  nv:=gen_random_uuid();
  insert into public.quiz_variants(id,tenant_id,quiz_set_id,variant_type,time_limit_minutes,total_marks)
   values(nv,p_tenant,dest,v.variant_type,v.time_limit_minutes,null);
  for l in select * from public.quiz_variant_questions where variant_id=v.id order by order_index,id loop
   select * into q from public.questions where id=l.question_id and tenant_id=p_tenant and created_by=p_actor;
   if not found or l.tenant_id<>p_tenant then raise exception 'quiz_no_access' using errcode='PT404'; end if;
   nq:=gen_random_uuid();
   -- Copy the full installed question shape, including existing figure_id and
   -- future additive fields. Reset identity and release state, never the source.
   payload:=to_jsonb(q)||jsonb_build_object('id',nq,'created_at',now(),'content_version',1,'release_locked',false,
    'origin_question_id',coalesce(q.origin_question_id,q.id),'source_quiz_id',coalesce(q.source_quiz_id,p_id));
   insert into public.questions select (jsonb_populate_record(null::public.questions,payload)).*;
   insert into public.quiz_variant_questions(tenant_id,variant_id,question_id,order_index,marks_override)
    values(p_tenant,nv,nq,l.order_index,l.marks_override);
  end loop;
 end loop;
 insert into public.quiz_copy_requests values(p_tenant,p_actor,p_key,p_id,p_title,dest);
 insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
  values(p_tenant,p_actor,'teacher','quiz.duplicated','quiz_set',dest,jsonb_build_object('source_quiz_id',p_id,'question_count',count_items));
 return jsonb_build_object('quiz_set_id',dest,'replayed',false);
end $$;

revoke all on function public.guard_released_question(),public.guard_released_structure(),
 public.assert_quiz_owner(uuid,uuid,uuid),public.quiz_publication_state(uuid,uuid,uuid),
 public.publish_quiz_atomic(uuid,uuid,uuid,text),public.copy_quiz_draft(uuid,uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.guard_released_question(),public.guard_released_structure(),
 public.assert_quiz_owner(uuid,uuid,uuid),public.quiz_publication_state(uuid,uuid,uuid),
 public.publish_quiz_atomic(uuid,uuid,uuid,text),public.copy_quiz_draft(uuid,uuid,uuid,uuid,text) to service_role;
commit;
notify pgrst,'reload schema';



-- Migration 52 — Level-aware batches, memberships and quiz assignments.
-- Apply after migrations 49-51 and the existing Course -> Level migration 47.
-- Browser roles remain denied; all application writes use the tenant-scoped API.
begin;

create unique index if not exists uq_courses_id_tenant
  on public.courses(id, tenant_id);
create unique index if not exists uq_quiz_sets_id_tenant
  on public.quiz_sets(id, tenant_id);

create table if not exists public.batches (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  course_id uuid not null,
  course_level_id uuid not null,
  name text not null,
  exam_session text,
  starts_on date,
  ends_on date,
  status text not null default 'active' check (status in ('active','archived')),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint batches_course_tenant_fk
    foreign key (course_id, tenant_id)
    references public.courses(id, tenant_id) on delete cascade,
  constraint batches_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references public.course_levels(id, tenant_id, course_id) on delete cascade,
  constraint batches_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  constraint batches_tenant_level_name_key
    unique (tenant_id, course_level_id, name),
  constraint batches_id_tenant_key unique (id, tenant_id),
  constraint batches_dates_check
    check (starts_on is null or ends_on is null or starts_on <= ends_on)
);
create index if not exists idx_batches_tenant_level
  on public.batches(tenant_id, course_id, course_level_id, status);

create table if not exists public.batch_memberships (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  batch_id uuid not null,
  profile_id uuid not null,
  membership_role text not null default 'student'
    check (membership_role in ('student','teacher')),
  active boolean not null default true,
  valid_from date,
  valid_to date,
  created_at timestamptz not null default now(),
  constraint batch_memberships_batch_tenant_fk
    foreign key (batch_id, tenant_id)
    references public.batches(id, tenant_id) on delete cascade,
  constraint batch_memberships_profile_tenant_fk
    foreign key (profile_id, tenant_id)
    references public.profiles(id, tenant_id) on delete cascade,
  constraint batch_memberships_tenant_batch_profile_key
    unique (tenant_id, batch_id, profile_id),
  constraint batch_memberships_dates_check
    check (valid_from is null or valid_to is null or valid_from <= valid_to)
);
create index if not exists idx_batch_memberships_member
  on public.batch_memberships(tenant_id, profile_id, active);
create index if not exists idx_batch_memberships_batch
  on public.batch_memberships(tenant_id, batch_id);

create table if not exists public.quiz_assignments (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  quiz_set_id uuid not null,
  batch_id uuid not null,
  available_from timestamptz,
  available_to timestamptz,
  status text not null default 'active' check (status in ('active','withdrawn')),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint quiz_assignments_quiz_tenant_fk
    foreign key (quiz_set_id, tenant_id)
    references public.quiz_sets(id, tenant_id) on delete cascade,
  constraint quiz_assignments_batch_tenant_fk
    foreign key (batch_id, tenant_id)
    references public.batches(id, tenant_id) on delete cascade,
  constraint quiz_assignments_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  constraint quiz_assignments_tenant_quiz_batch_key
    unique (tenant_id, quiz_set_id, batch_id),
  constraint quiz_assignments_window_check
    check (available_from is null or available_to is null or available_from <= available_to)
);
create index if not exists idx_quiz_assignments_batch
  on public.quiz_assignments(tenant_id, batch_id, status);
create index if not exists idx_quiz_assignments_quiz
  on public.quiz_assignments(tenant_id, quiz_set_id);

alter table public.quiz_sets
  add column if not exists audience_mode text not null default 'legacy_course';
do $$ begin
  alter table public.quiz_sets add constraint quiz_sets_audience_mode_check
    check (audience_mode in ('legacy_course','assigned_batches'));
exception when duplicate_object then null; end $$;

alter table public.batches enable row level security;
alter table public.batch_memberships enable row level security;
alter table public.quiz_assignments enable row level security;

revoke all on table public.batches, public.batch_memberships,
  public.quiz_assignments from public, anon, authenticated;
grant select, insert, update, delete on table public.batches,
  public.batch_memberships, public.quiz_assignments to service_role;

drop policy if exists "read own tenant batches" on public.batches;
create policy "read own tenant batches" on public.batches
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) or (select public.is_super_admin()));
drop policy if exists "institution admins manage batches" on public.batches;
create policy "institution admins manage batches" on public.batches
  for all to authenticated
  using (tenant_id = (select public.current_tenant_id())
         and (select public.current_role_name()) = 'institution_admin')
  with check (tenant_id = (select public.current_tenant_id())
              and (select public.current_role_name()) = 'institution_admin');

drop policy if exists "read own membership or admin" on public.batch_memberships;
create policy "read own membership or admin" on public.batch_memberships
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) and
         (profile_id = (select auth.uid()) or
          (select public.current_role_name()) = 'institution_admin'));
drop policy if exists "institution admins manage memberships" on public.batch_memberships;
create policy "institution admins manage memberships" on public.batch_memberships
  for all to authenticated
  using (tenant_id = (select public.current_tenant_id())
         and (select public.current_role_name()) = 'institution_admin')
  with check (tenant_id = (select public.current_tenant_id())
              and (select public.current_role_name()) = 'institution_admin');

drop policy if exists "staff read assignments" on public.quiz_assignments;
create policy "staff read assignments" on public.quiz_assignments
  for select to authenticated
  using (tenant_id = (select public.current_tenant_id()) and (select public.is_staff()));

commit;
notify pgrst, 'reload schema';
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
-- Migration 54 — scoring policies and atomic attempt snapshots.
-- Apply after migration 53. Existing quizzes keep default full/zero scoring.
begin;

create table if not exists public.scoring_policies (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references public.tenants(id) on delete cascade,
  name       text not null,
  rules      jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
  created_by uuid,
  created_at timestamptz not null default now(),
  constraint scoring_policies_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  unique (tenant_id, name),
  unique (id, tenant_id)
);
create index if not exists idx_scoring_policies_tenant
  on public.scoring_policies(tenant_id);

alter table public.quiz_sets add column if not exists scoring_policy_id uuid;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'quiz_sets_scoring_policy_tenant_fk'
      and conrelid = 'public.quiz_sets'::regclass
  ) then
    alter table public.quiz_sets
      add constraint quiz_sets_scoring_policy_tenant_fk
      foreign key (scoring_policy_id, tenant_id)
      references public.scoring_policies(id, tenant_id) on delete set null (scoring_policy_id);
  end if;
end $$;

alter table public.quiz_attempts
  add column if not exists scoring_policy_snapshot jsonb;
alter table public.practice_sessions
  add column if not exists scoring_policy_snapshot jsonb;

alter table public.scoring_policies enable row level security;
revoke all on public.scoring_policies from public, anon, authenticated;
grant select, insert, update, delete on public.scoring_policies to service_role;

drop policy if exists "read own tenant scoring policies" on public.scoring_policies;
create policy "read own tenant scoring policies" on public.scoring_policies
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "institution admins manage scoring policies" on public.scoring_policies;
create policy "institution admins manage scoring policies" on public.scoring_policies
  for all using (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.tenant_id = scoring_policies.tenant_id
        and p.role = 'institution_admin'
    )
  ) with check (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid() and p.tenant_id = scoring_policies.tenant_id
        and p.role = 'institution_admin'
    )
  );

-- Keep attempt-limit enforcement, the exact question paper, and the scoring
-- rules in one transaction. The six-argument version remains during rollout so
-- an older backend can coexist until the new deployment is healthy.
drop function if exists public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
);
create function public.create_limited_quiz_attempt(
  p_tenant_id uuid,
  p_variant_id uuid,
  p_student_id uuid,
  p_started_at timestamptz,
  p_max_attempts integer,
  p_question_snapshot jsonb,
  p_scoring_policy_snapshot jsonb
)
returns uuid
language plpgsql
security invoker
set search_path = ''
as $$
declare
  created_id uuid;
begin
  if p_max_attempts < 1 then
    raise exception 'quiz_attempt_limit_invalid' using errcode = '22023';
  end if;
  if jsonb_typeof(p_question_snapshot) <> 'array'
     or jsonb_array_length(p_question_snapshot) < 1 then
    raise exception 'quiz_attempt_snapshot_invalid' using errcode = '22023';
  end if;
  if p_scoring_policy_snapshot is not null
     and jsonb_typeof(p_scoring_policy_snapshot) <> 'object' then
    raise exception 'scoring_policy_snapshot_invalid' using errcode = '22023';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(
      p_student_id::text || ':' || p_variant_id::text,
      0
    )
  );
  if (
    select count(*) >= p_max_attempts
    from public.quiz_attempts attempts
    where attempts.tenant_id = p_tenant_id
      and attempts.student_id = p_student_id
      and attempts.variant_id = p_variant_id
  ) then
    raise exception 'quiz_attempt_limit_reached' using errcode = '23514';
  end if;

  insert into public.quiz_attempts (
    tenant_id, variant_id, student_id, status, started_at,
    question_snapshot, scoring_policy_snapshot
  ) values (
    p_tenant_id, p_variant_id, p_student_id, 'in_progress', p_started_at,
    p_question_snapshot, p_scoring_policy_snapshot
  ) returning id into created_id;
  return created_id;
end;
$$;

revoke all on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
) from public, anon, authenticated;
grant execute on function public.create_limited_quiz_attempt(
  uuid, uuid, uuid, timestamptz, integer, jsonb, jsonb
) to service_role;

commit;
notify pgrst, 'reload schema';
-- Migration 55 — Course exam scoring standard (Phase 6.2-EX)
-- Apply after migration 54. Binds a policy to a COURSE LEVEL, because one course
-- may have Foundation, Intermediate and Final levels with different rules.
-- The exam simulator scores by that level's real exam standard (e.g. CA Foundation
-- −0.25 vs CMA no negative marking) instead of a single tenant-wide value.
-- Additive + nullable: NULL (every existing course level) = today's exam-config
-- negative marking, and it is only consulted when SCORING_POLICIES_ENABLED is on.
begin;

alter table public.course_levels add column if not exists exam_scoring_policy_id uuid;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'course_levels_exam_policy_tenant_fk'
      and conrelid = 'public.course_levels'::regclass
  ) then
    alter table public.course_levels
      add constraint course_levels_exam_policy_tenant_fk
      foreign key (exam_scoring_policy_id, tenant_id)
      references public.scoring_policies(id, tenant_id) on delete set null (exam_scoring_policy_id);
  end if;
end $$;

commit;
notify pgrst, 'reload schema';
-- Migration 56 - Paper profiles (Phase 6.3-D, commerce vertical pack)
-- Apply after migration 55. Additive + nullable + flag-gated: a course level with
-- no paper profile (every existing course level) generates exactly as today, and the
-- profile is only read into the generation prompt when COMMERCE_PACK_ENABLED is
-- on. It is the single place commerce context lives (exam body / level / paper /
-- assessment year / accounting framework), consulted by generation (B) and the
-- P6.2 exam standards. Backend writes via the service-role key; RLS mirrors
-- scoring_policies (read within tenant, staff manage).
begin;

create table if not exists public.paper_profiles (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id) on delete cascade,
  course_id       uuid not null,
  course_level_id uuid not null,
  exam_body       text,   -- e.g. ICAI, ICMAI, ICSI, ACCA, IMA
  level           text,   -- e.g. Foundation, Intermediate, Final
  paper           text,   -- e.g. Paper 4 - Business Economics
  assessment_year text,   -- e.g. 2025-26 (the applicable exam period)
  framework       text,   -- e.g. Indian GAAP, Ind AS, IFRS, US GAAP
  created_by      uuid,
  created_at      timestamptz not null default now(),
  constraint paper_profiles_course_tenant_fk
    foreign key (course_id, tenant_id)
    references public.courses(id, tenant_id) on delete cascade,
  constraint paper_profiles_level_scope_fk
    foreign key (course_level_id, tenant_id, course_id)
    references public.course_levels(id, tenant_id, course_id) on delete cascade,
  constraint paper_profiles_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete set null (created_by),
  unique (tenant_id, course_level_id)
);
create index if not exists idx_paper_profiles_tenant on public.paper_profiles(tenant_id);
create index if not exists idx_paper_profiles_course on public.paper_profiles(course_id);
create index if not exists idx_paper_profiles_level on public.paper_profiles(course_level_id);

alter table public.paper_profiles enable row level security;
revoke all on public.paper_profiles from public, anon, authenticated;
grant select, insert, update, delete on public.paper_profiles to service_role;
drop policy if exists "read own tenant paper profiles" on public.paper_profiles;
create policy "read own tenant paper profiles" on public.paper_profiles
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "institution admins manage paper profiles" on public.paper_profiles;
create policy "institution admins manage paper profiles" on public.paper_profiles
  for all using (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and p.tenant_id = paper_profiles.tenant_id
        and p.role = 'institution_admin'
    )
  ) with check (
    tenant_id = current_tenant_id()
    and exists (
      select 1 from public.profiles p
      where p.id = auth.uid()
        and p.tenant_id = paper_profiles.tenant_id
        and p.role = 'institution_admin'
    )
  );

commit;
notify pgrst, 'reload schema';

-- ============================================================================
-- END OF INTEGRATED FEATURES
-- ============================================================================

-- Atomic audience selection at publication (migration 67).
create or replace function public.publish_quiz_to_batches_atomic(
 p_id uuid, p_tenant uuid, p_actor uuid, p_token text, p_batch_ids uuid[], p_require_managed boolean
) returns jsonb
language plpgsql security invoker set search_path=public as $$
declare s public.quiz_sets; chosen uuid[]; batch_count integer;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 if s.status='published' and s.last_publication_token=p_token
    and s.audience_mode='assigned_batches' then return to_jsonb(s); end if;
 if s.status='published' then raise exception 'quiz_changed' using errcode='PT409'; end if;
 select array_agg(distinct batch_id) into chosen from unnest(p_batch_ids) batch_id;
 if chosen is null or cardinality(chosen)<>cardinality(p_batch_ids) then
  raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
 select count(*) into batch_count from public.batches b
  join public.subjects subject on subject.id=s.subject_id and subject.tenant_id=p_tenant
  where b.id=any(chosen) and b.tenant_id=p_tenant and b.status='active'
   and b.course_id=subject.course_id and b.course_level_id=subject.course_level_id;
 if batch_count<>cardinality(chosen) then
  raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
 if p_require_managed and exists(
  select 1 from unnest(chosen) selected(id) where not exists(
   select 1 from public.batch_memberships member
   where member.batch_id=selected.id and member.tenant_id=p_tenant
    and member.profile_id=p_actor and member.membership_role='teacher' and member.active
  ) then raise exception 'quiz_batch_access' using errcode='PT403'; end if;
 perform public.publish_quiz_atomic(p_id,p_tenant,p_actor,p_token);
 insert into public.quiz_assignments(tenant_id,quiz_set_id,batch_id,created_by,status)
 select p_tenant,p_id,batch_id,p_actor,'active' from unnest(chosen) batch_id
 on conflict (tenant_id,quiz_set_id,batch_id) do update set status='active';
 update public.quiz_sets set audience_mode='assigned_batches'
  where id=p_id and tenant_id=p_tenant returning * into s;
 return to_jsonb(s);
end $$;
revoke all on function public.publish_quiz_to_batches_atomic(uuid,uuid,uuid,text,uuid[],boolean)
 from public,anon,authenticated;
grant execute on function public.publish_quiz_to_batches_atomic(uuid,uuid,uuid,text,uuid[],boolean)
 to service_role;

-- Migration 77: tenant paper formats and durable generated exam papers.
alter table public.paper_profiles
 add column if not exists format_config jsonb not null default '{}'::jsonb;
alter table public.paper_profiles drop constraint if exists paper_profiles_format_config_object;
alter table public.paper_profiles add constraint paper_profiles_format_config_object
 check(jsonb_typeof(format_config)='object');

create unique index if not exists uq_course_levels_id_tenant
 on public.course_levels(id,tenant_id);

create table if not exists public.generated_papers(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 course_level_id uuid not null,
 subject_id uuid not null,
 mode text not null check(mode in('exact_mark','candidate_ai')),
 requested_total_marks numeric not null check(requested_total_marks>0 and requested_total_marks*2=trunc(requested_total_marks*2)),
 selected_question_ids uuid[] not null default '{}'::uuid[],
 status text not null default 'pending' check(status in('pending','processing','ready','failed')),
 instructions_text text,
 paper_payload jsonb check(paper_payload is null or jsonb_typeof(paper_payload)='object'),
 error_message text,
 created_by uuid not null,
 created_at timestamptz not null default now(),
 completed_at timestamptz,
 constraint generated_papers_level_tenant_fk foreign key(course_level_id,tenant_id)
  references public.course_levels(id,tenant_id) on delete cascade,
 constraint generated_papers_subject_tenant_fk foreign key(subject_id,tenant_id)
  references public.subjects(id,tenant_id) on delete cascade,
 constraint generated_papers_creator_tenant_fk foreign key(created_by,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade
);
create index if not exists generated_papers_history on public.generated_papers(tenant_id,course_level_id,created_at desc);
create index if not exists generated_papers_owner on public.generated_papers(tenant_id,created_by,created_at desc);
alter table public.generated_papers enable row level security;
revoke all on public.generated_papers from public,anon,authenticated;
grant select,insert,update,delete on public.generated_papers to service_role;
create policy "read own tenant generated papers" on public.generated_papers for select
 using(tenant_id=current_tenant_id() or is_super_admin());
create policy "staff manage generated papers" on public.generated_papers for all
 using(tenant_id=current_tenant_id() and is_staff())
 with check(tenant_id=current_tenant_id() and is_staff());

alter table public.faculty_jobs drop constraint if exists faculty_jobs_kind_check;
alter table public.faculty_jobs add constraint faculty_jobs_kind_check
 check(kind in('blueprint','analysis_quiz','extraction','regenerate_set','generate_paper'));
alter table public.ai_rate_limits drop constraint if exists ai_rate_limits_endpoint_check;
alter table public.ai_rate_limits add constraint ai_rate_limits_endpoint_check check(endpoint in(
 'quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
 'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation'
));

create or replace function public.consume_ai_rate_limit(
 p_tenant_id uuid,p_user_id uuid,p_endpoint text,p_limit integer
) returns table(allowed boolean,retry_after_seconds integer,remaining integer)
language plpgsql security invoker set search_path='' as $$
declare request_time timestamptz:=clock_timestamp(); consumed_count integer; active_window_start timestamptz;
begin
 if p_limit<1 then raise exception 'Rate limit must be a positive integer'; end if;
 if p_endpoint not in('quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
  'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation')
  then raise exception 'Unknown rate-limit endpoint'; end if;
 insert into public.ai_rate_limits as limits(tenant_id,user_id,endpoint,window_started_at,request_count,updated_at)
 values(p_tenant_id,p_user_id,p_endpoint,request_time,1,request_time)
 on conflict(tenant_id,user_id,endpoint) do update set
  window_started_at=case when limits.window_started_at<=request_time-interval '1 hour' then request_time else limits.window_started_at end,
  request_count=case when limits.window_started_at<=request_time-interval '1 hour' then 1 else limits.request_count+1 end,
  updated_at=request_time
 where limits.window_started_at<=request_time-interval '1 hour' or limits.request_count<p_limit
 returning limits.request_count,limits.window_started_at into consumed_count,active_window_start;
 if found then return query select true,0,greatest(p_limit-consumed_count,0); return; end if;
 select limits.window_started_at into active_window_start from public.ai_rate_limits limits
  where limits.tenant_id=p_tenant_id and limits.user_id=p_user_id and limits.endpoint=p_endpoint;
 return query select false,greatest(1,ceil(extract(epoch from(active_window_start+interval '1 hour'-request_time)))::integer),0;
end $$;

create or replace function public.enqueue_generated_paper_job(
 p_id uuid,p_tenant uuid,p_actor uuid,p_key uuid,p_request jsonb,p_hash text,p_limit integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare existing public.faculty_jobs; created public.faculty_jobs; quota record;
 requested_subject_id uuid:=nullif(p_request->>'subject_id','')::uuid;
 requested_level_id uuid:=nullif(p_request->>'course_level_id','')::uuid;
 requested numeric:=nullif(p_request->>'requested_total_marks','')::numeric;
 selected_mode text:=p_request->>'mode';
begin
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_tenant::text||p_actor::text||p_key::text,0));
 select * into existing from public.faculty_jobs where tenant_id=p_tenant and created_by=p_actor and request_key=p_key;
 if found then
  if existing.request_hash<>p_hash or existing.kind<>'generate_paper' then return jsonb_build_object('conflict',true); end if;
  return to_jsonb(existing);
 end if;
 if selected_mode not in('exact_mark','candidate_ai') or requested<=0 or requested*2<>trunc(requested*2)
  then raise exception 'Invalid paper request'; end if;
 if not exists(select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
    where p.id=p_actor and p.tenant_id=p_tenant and p.role='teacher' and t.is_active)
  or not exists(select 1 from public.teacher_subjects a where a.tenant_id=p_tenant and a.teacher_id=p_actor and a.subject_id=requested_subject_id)
  or not exists(select 1 from public.subjects s where s.id=requested_subject_id and s.tenant_id=p_tenant and s.course_level_id=requested_level_id)
  or not exists(select 1 from public.paper_profiles p where p.tenant_id=p_tenant and p.course_level_id=requested_level_id)
  then raise exception 'Paper scope unavailable'; end if;
 select * into quota from public.consume_ai_rate_limit(p_tenant,p_actor,'paper_generation',p_limit);
 if not quota.allowed then return jsonb_build_object('rate_limited',true,'retry_after_seconds',quota.retry_after_seconds); end if;
 insert into public.generated_papers(id,tenant_id,course_level_id,subject_id,mode,requested_total_marks,created_by)
 values(p_id,p_tenant,requested_level_id,requested_subject_id,selected_mode,requested,p_actor);
 p_request:=p_request||jsonb_build_object('generated_paper_id',p_id);
 insert into public.faculty_jobs(tenant_id,created_by,request_key,request_hash,kind,request)
 values(p_tenant,p_actor,p_key,p_hash,'generate_paper',p_request) returning * into created;
 return to_jsonb(created);
end $$;
revoke all on function public.consume_ai_rate_limit(uuid,uuid,text,integer),
 public.enqueue_generated_paper_job(uuid,uuid,uuid,uuid,jsonb,text,integer) from public,anon,authenticated;
grant execute on function public.consume_ai_rate_limit(uuid,uuid,text,integer),
 public.enqueue_generated_paper_job(uuid,uuid,uuid,uuid,jsonb,text,integer) to service_role;

-- Migration 78: native handwritten-answer evaluation Phase A.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values
 ('evaluation-papers','evaluation-papers',false,31457280,
  array['application/pdf','image/png','image/jpeg']),
 ('evaluation-submissions','evaluation-submissions',false,31457280,
  array['application/pdf','image/png','image/jpeg'])
on conflict(id) do update set
 public=false,
 file_size_limit=excluded.file_size_limit,
 allowed_mime_types=excluded.allowed_mime_types;

create unique index if not exists uq_generated_papers_id_tenant
 on public.generated_papers(id,tenant_id);
create unique index if not exists uq_subjects_id_tenant_level
 on public.subjects(id,tenant_id,course_level_id);

create table if not exists public.evaluation_papers(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 course_level_id uuid not null,
 subject_id uuid not null,
 title text not null check(char_length(trim(title)) between 1 and 200),
 question_paper_storage_path text not null unique,
 suggested_answer_storage_path text unique,
 total_marks numeric not null check(total_marks>0),
 generated_paper_id uuid,
 rubric_status text not null default 'not_started' check(rubric_status in('not_started')),
 is_active boolean not null default true,
 created_by uuid not null,
 created_at timestamptz not null default now(),
 constraint evaluation_papers_subject_level_tenant_fk
  foreign key(subject_id,tenant_id,course_level_id)
  references public.subjects(id,tenant_id,course_level_id) on delete cascade,
 constraint evaluation_papers_generated_tenant_fk
  foreign key(generated_paper_id,tenant_id)
  references public.generated_papers(id,tenant_id) on delete set null(generated_paper_id),
 constraint evaluation_papers_creator_tenant_fk
  foreign key(created_by,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 unique(id,tenant_id)
);
create index if not exists evaluation_papers_catalog
 on public.evaluation_papers(tenant_id,course_level_id,subject_id,created_at desc);

create table if not exists public.evaluation_upload_intents(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 evaluation_paper_id uuid not null,
 storage_path text not null unique,
 original_filename text not null check(char_length(original_filename) between 1 and 255),
 content_type text not null check(content_type in('application/pdf','image/png','image/jpeg')),
 expected_size bigint not null check(expected_size between 1 and 31457280),
 status text not null default 'pending' check(status in('pending','verified','consumed','failed')),
 expires_at timestamptz not null default(now()+interval '2 hours'),
 verified_at timestamptz,
 created_at timestamptz not null default now(),
 constraint evaluation_intents_student_tenant_fk
  foreign key(student_id,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 constraint evaluation_intents_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id) on delete cascade,
 unique(id,tenant_id,student_id,evaluation_paper_id)
);
create index if not exists evaluation_intents_owner
 on public.evaluation_upload_intents(tenant_id,student_id,created_at desc);
create index if not exists evaluation_intents_expiry
 on public.evaluation_upload_intents(expires_at) where status='pending';

create table if not exists public.handwritten_submissions(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 evaluation_paper_id uuid not null,
 upload_intent_id uuid not null unique,
 answer_script_path text not null unique,
 additional_pages_path text,
 status text not null default 'pending' check(status in(
  'pending','queued','processing','pending_stage1','evaluated','review','failed'
 )),
 error_message text,
 retrigger_count integer not null default 0 check(retrigger_count>=0),
 regraded_from uuid,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint handwritten_submissions_intent_scope_fk
  foreign key(upload_intent_id,tenant_id,student_id,evaluation_paper_id)
  references public.evaluation_upload_intents(id,tenant_id,student_id,evaluation_paper_id)
  on delete restrict,
 constraint handwritten_submissions_student_tenant_fk
  foreign key(student_id,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_submissions_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id) on delete cascade,
 unique(id,tenant_id,student_id)
);
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_regraded_scope_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_regraded_scope_fk
 foreign key(regraded_from,tenant_id,student_id)
 references public.handwritten_submissions(id,tenant_id,student_id)
 on delete set null(regraded_from);
create index if not exists handwritten_submissions_owner
 on public.handwritten_submissions(tenant_id,student_id,created_at desc);
create index if not exists handwritten_submissions_paper
 on public.handwritten_submissions(tenant_id,evaluation_paper_id,created_at desc);

create table if not exists public.evaluation_jobs(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 submission_id uuid not null unique,
 kind text not null default 'evaluate_submission' check(kind in('evaluate_submission')),
 status text not null default 'queued' check(status in('queued','claimed','processing','done','failed')),
 owner_student_id uuid not null,
 claimed_by uuid,
 claimed_at timestamptz,
 lease_expires_at timestamptz,
 attempts integer not null default 0 check(attempts between 0 and 3),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint evaluation_jobs_submission_scope_fk
  foreign key(submission_id,tenant_id,owner_student_id)
  references public.handwritten_submissions(id,tenant_id,student_id) on delete cascade
);
create index if not exists evaluation_jobs_queue
 on public.evaluation_jobs(status,created_at)
 where status in('queued','claimed','processing');
create index if not exists evaluation_jobs_owner
 on public.evaluation_jobs(tenant_id,owner_student_id,created_at desc);

alter table public.evaluation_papers enable row level security;
alter table public.evaluation_upload_intents enable row level security;
alter table public.handwritten_submissions enable row level security;
alter table public.evaluation_jobs enable row level security;
revoke all on public.evaluation_papers,public.evaluation_upload_intents,
 public.handwritten_submissions,public.evaluation_jobs from public,anon,authenticated;
grant select,insert,update,delete on public.evaluation_papers,
 public.evaluation_upload_intents,public.handwritten_submissions,public.evaluation_jobs
 to service_role;

drop policy if exists "staff read tenant evaluation papers" on public.evaluation_papers;
create policy "staff read tenant evaluation papers" on public.evaluation_papers
 for select using(tenant_id=current_tenant_id() and is_staff());
drop policy if exists "staff manage tenant evaluation papers" on public.evaluation_papers;
create policy "staff manage tenant evaluation papers" on public.evaluation_papers
 for all using(tenant_id=current_tenant_id() and is_staff())
 with check(tenant_id=current_tenant_id() and is_staff());
drop policy if exists "owners read evaluation intents" on public.evaluation_upload_intents;
create policy "owners read evaluation intents" on public.evaluation_upload_intents
 for select using(tenant_id=current_tenant_id() and (student_id=auth.uid() or is_staff()));
drop policy if exists "owners read handwritten submissions" on public.handwritten_submissions;
create policy "owners read handwritten submissions" on public.handwritten_submissions
 for select using(tenant_id=current_tenant_id() and (student_id=auth.uid() or is_staff()));
drop policy if exists "owners read evaluation jobs" on public.evaluation_jobs;
create policy "owners read evaluation jobs" on public.evaluation_jobs
 for select using(tenant_id=current_tenant_id() and (owner_student_id=auth.uid() or is_staff()));

create or replace function public.create_handwritten_submission_job(
 p_tenant uuid,p_student uuid,p_intent uuid
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents;
 submission public.handwritten_submissions;
 job public.evaluation_jobs;
begin
 perform pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(p_tenant::text||':'||p_student::text||':'||p_intent::text,0)
 );
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 select * into submission from public.handwritten_submissions
  where upload_intent_id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if found then
  select * into job from public.evaluation_jobs where submission_id=submission.id;
  return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
 end if;
 if intent.status<>'verified' or intent.expires_at<=now() then
  raise exception 'evaluation_intent_not_verified' using errcode='PT409';
 end if;
 if not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
   where p.id=p_student and p.tenant_id=p_tenant and p.role='student' and t.is_active
 ) or not exists(
  select 1 from public.evaluation_papers ep
  join public.subjects s on s.id=ep.subject_id and s.tenant_id=ep.tenant_id
  join public.enrollments e on e.tenant_id=ep.tenant_id
   and e.profile_id=p_student and e.course_id=s.course_id
   and e.course_level_id=ep.course_level_id
  where ep.id=intent.evaluation_paper_id and ep.tenant_id=p_tenant and ep.is_active
 ) then raise exception 'evaluation_access_denied' using errcode='PT403'; end if;
 insert into public.handwritten_submissions(
  tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,status
 ) values(p_tenant,p_student,intent.evaluation_paper_id,intent.id,intent.storage_path,'queued')
 returning * into submission;
 update public.evaluation_upload_intents set status='consumed'
  where id=intent.id and tenant_id=p_tenant and student_id=p_student;
 insert into public.evaluation_jobs(tenant_id,submission_id,owner_student_id)
 values(p_tenant,submission.id,p_student) returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set
  status='failed',claimed_by=null,lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set
  status='failed',error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j
  where j.submission_id=s.id and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3
  order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set
  status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
 where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status='claimed' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 if not exists(
  select 1 from public.handwritten_submissions s
  join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and s.student_id=selected.owner_student_id and p.role='student'
 ) then return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now() where id=selected.id;
 update public.handwritten_submissions set status='processing',error_message=null,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 return true;
end $$;

create or replace function public.finish_evaluation_stub_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status='processing' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 update public.handwritten_submissions set
  status='pending_stage1',error_message=null,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 if not found then return false; end if;
 update public.evaluation_jobs set
  status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_job(
 p_id uuid,p_worker uuid,p_retryable boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status in('claimed','processing') and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 update public.evaluation_jobs set
  status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation preparation failed.' end,
  updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 return true;
end $$;

revoke all on function public.create_handwritten_submission_job(uuid,uuid,uuid),
 public.claim_evaluation_job(uuid),public.start_evaluation_job(uuid,uuid),
 public.finish_evaluation_stub_job(uuid,uuid),
 public.fail_evaluation_job(uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function public.create_handwritten_submission_job(uuid,uuid,uuid),
 public.claim_evaluation_job(uuid),public.start_evaluation_job(uuid,uuid),
 public.finish_evaluation_stub_job(uuid,uuid),
 public.fail_evaluation_job(uuid,uuid,boolean) to service_role;

commit;
notify pgrst,'reload schema';

-- Migration 79: handwritten evaluation Stage 1 OCR/transcription.
begin;
alter table public.handwritten_submissions
 add column if not exists stage1_extraction jsonb not null default '{}'::jsonb,
 add column if not exists stage1_extraction_source text,
 add column if not exists page_mapping jsonb;
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','evaluated','review','failed'
 ));

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set status='failed',claimed_by=null,
  lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set status='failed',
  error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j where j.submission_id=s.id
  and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing','pending_stage1','processing_stage1');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3 order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if not exists(select 1 from public.handwritten_submissions s
  join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
  join public.tenants t on t.id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and s.student_id=selected.owner_student_id and p.role='student'
   and t.is_active and t.handwritten_evaluation_enabled) then return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now() where id=selected.id;
 update public.handwritten_submissions set status='processing_stage1',
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 return true;
end $$;
create or replace function public.heartbeat_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 update public.evaluation_jobs set lease_expires_at=now()+interval '120 seconds',
  updated_at=now() where id=p_id and status in('claimed','processing')
  and claimed_by=p_worker and lease_expires_at>now();
 return found;
end $$;
create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,
 p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if jsonb_typeof(p_extraction)<>'object' or p_source is null or p_source='' then return false; end if;
 update public.handwritten_submissions set stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,
  page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
  status=case when p_requires_review then 'review' else 'stage1_complete' end,
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 if not found then return false; end if;
 update public.evaluation_jobs set status='done',claimed_by=null,
  lease_expires_at=null,updated_at=now() where id=selected.id;
 return true;
end $$;
revoke all on function public.heartbeat_evaluation_job(uuid,uuid),
 public.finish_evaluation_stage1_job(uuid,uuid,jsonb,text,jsonb,boolean)
 from public,anon,authenticated;
grant execute on function public.heartbeat_evaluation_job(uuid,uuid),
 public.finish_evaluation_stage1_job(uuid,uuid,jsonb,text,jsonb,boolean)
 to service_role;

commit;
notify pgrst,'reload schema';
-- Phase E: frozen handwritten-evaluation rubric generation.
begin;

alter table public.evaluation_papers
 add column if not exists structured_qa jsonb not null default '{}'::jsonb,
 add column if not exists question_structure jsonb,
 add column if not exists rubric_source text,
 add column if not exists rubric_error text not null default '',
 add column if not exists question_paper_text text,
 add column if not exists suggested_answer_text text;

alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_rubric_status_check;
alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_rubric_source_check,
 drop constraint if exists evaluation_papers_structured_qa_json_check,
 drop constraint if exists evaluation_papers_question_structure_json_check;
alter table public.evaluation_papers
 add constraint evaluation_papers_rubric_status_check check(
  rubric_status in('not_started','extracting','generating','ready','failed')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_rubric_source_check check(
  rubric_source is null or rubric_source in('official','ai_derived')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_structured_qa_json_check check(
  jsonb_typeof(structured_qa) in('object','array')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_question_structure_json_check check(
  question_structure is null or jsonb_typeof(question_structure)='object'
 );
create unique index if not exists uq_evaluation_papers_creator_scope
 on public.evaluation_papers(id,tenant_id,created_by);

alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_submission_scope_fk;
alter table public.evaluation_jobs
 alter column submission_id drop not null,
 alter column owner_student_id drop not null,
 add column if not exists evaluation_paper_id uuid,
 add column if not exists owner_teacher_id uuid;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_submission_scope_fk
  foreign key(submission_id,tenant_id,owner_student_id)
  references public.handwritten_submissions(id,tenant_id,student_id) on delete cascade;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_paper_scope_fk;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_paper_scope_fk
  foreign key(evaluation_paper_id,tenant_id,owner_teacher_id)
  references public.evaluation_papers(id,tenant_id,created_by) on delete cascade;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_kind_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_kind_check check(
  kind in('evaluate_submission','build_rubric')
 );
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_target_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_target_check check(
  (kind='evaluate_submission' and submission_id is not null
   and owner_student_id is not null and evaluation_paper_id is null
   and owner_teacher_id is null)
  or
  (kind='build_rubric' and submission_id is null
   and owner_student_id is null and evaluation_paper_id is not null
   and owner_teacher_id is not null)
 );
create unique index if not exists uq_evaluation_jobs_rubric_paper
 on public.evaluation_jobs(evaluation_paper_id)
 where kind='build_rubric';
create index if not exists evaluation_jobs_teacher_owner
 on public.evaluation_jobs(tenant_id,owner_teacher_id,created_at desc)
 where owner_teacher_id is not null;

drop policy if exists "owners read evaluation jobs" on public.evaluation_jobs;
create policy "owners read evaluation jobs" on public.evaluation_jobs
 for select using(
  tenant_id=current_tenant_id()
  and (owner_student_id=auth.uid() or owner_teacher_id=auth.uid() or is_staff())
 );

create or replace function public.enqueue_evaluation_rubric_job()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 perform pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(new.tenant_id::text||':rubric:'||new.id::text,0)
 );
 if not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
  where p.id=new.created_by and p.tenant_id=new.tenant_id and p.role='teacher'
   and t.is_active and t.handwritten_evaluation_enabled
 ) then
  raise exception 'rubric_job_teacher_not_authorized' using errcode='PT403';
 end if;
 insert into public.evaluation_jobs(
  tenant_id,evaluation_paper_id,owner_teacher_id,kind
 ) values(new.tenant_id,new.id,new.created_by,'build_rubric')
 on conflict(evaluation_paper_id) where kind='build_rubric' do nothing;
 return new;
end $$;
drop trigger if exists enqueue_evaluation_rubric_job on public.evaluation_papers;
create trigger enqueue_evaluation_rubric_job
 after insert on public.evaluation_papers for each row
 execute function public.enqueue_evaluation_rubric_job();

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set status='failed',claimed_by=null,
  lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set status='failed',
  error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j where j.submission_id=s.id
  and j.kind='evaluate_submission' and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing','pending_stage1','processing_stage1');
 update public.evaluation_papers p set rubric_status='failed',
  rubric_error='Rubric generation could not finish after repeated interruptions.'
 where exists(select 1 from public.evaluation_jobs j where j.evaluation_paper_id=p.id
  and j.tenant_id=p.tenant_id and j.kind='build_rubric'
  and j.status='failed' and j.attempts>=3)
  and p.rubric_status in('not_started','extracting','generating');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3 order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  if not exists(select 1 from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled) then return false; end if;
  update public.handwritten_submissions set status='processing_stage1',
   error_message=null,updated_at=now() where id=selected.submission_id
   and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 elsif selected.kind='build_rubric' then
  if not exists(select 1 from public.evaluation_papers ep
   join public.profiles p on p.id=ep.created_by and p.tenant_id=ep.tenant_id
   join public.tenants t on t.id=ep.tenant_id
   where ep.id=selected.evaluation_paper_id and ep.tenant_id=selected.tenant_id
    and ep.created_by=selected.owner_teacher_id and ep.is_active and p.role='teacher'
    and t.is_active and t.handwritten_evaluation_enabled
    and ep.rubric_status not in('ready')) then return false; end if;
  update public.evaluation_papers set rubric_status='extracting',rubric_error=''
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
    and created_by=selected.owner_teacher_id;
 else return false;
 end if;
 update public.evaluation_jobs set status='processing',updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.checkpoint_evaluation_rubric_texts(
 p_id uuid,p_worker uuid,p_question_text text,p_answer_text text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status='processing' and claimed_by=p_worker
  and lease_expires_at>now() for update;
 if not found or nullif(trim(p_question_text),'') is null then return false; end if;
 update public.evaluation_papers set question_paper_text=p_question_text,
  suggested_answer_text=nullif(p_answer_text,''),rubric_status='generating',rubric_error=''
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 return found;
end $$;

create or replace function public.finish_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_structured_qa jsonb,p_structure jsonb,p_source text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status='processing' and claimed_by=p_worker
  and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_structured_qa)<>'array'
  or (p_structure is not null and jsonb_typeof(p_structure)<>'object')
  or p_source not in('official','ai_derived') then return false; end if;
 update public.evaluation_papers set structured_qa=p_structured_qa,
  question_structure=p_structure,rubric_source=p_source,rubric_status='ready',
  rubric_error='' where id=selected.evaluation_paper_id
  and tenant_id=selected.tenant_id and created_by=selected.owner_teacher_id;
 if not found then return false; end if;
 update public.evaluation_jobs set status='done',claimed_by=null,
  lease_expires_at=null,updated_at=now() where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_retryable boolean,p_error text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status in('claimed','processing')
  and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.evaluation_papers set
  rubric_status=case when retrying then 'not_started' else 'failed' end,
  rubric_error=case when retrying then '' else left(coalesce(p_error,'Rubric generation failed.'),2000) end
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 return true;
end $$;

revoke all on function public.enqueue_evaluation_rubric_job(),
 public.checkpoint_evaluation_rubric_texts(uuid,uuid,text,text),
 public.finish_evaluation_rubric_job(uuid,uuid,jsonb,jsonb,text),
 public.fail_evaluation_rubric_job(uuid,uuid,boolean,text)
 from public,anon,authenticated;
grant execute on function public.checkpoint_evaluation_rubric_texts(uuid,uuid,text,text),
 public.finish_evaluation_rubric_job(uuid,uuid,jsonb,jsonb,text),
 public.fail_evaluation_rubric_job(uuid,uuid,boolean,text)
 to service_role;

commit;
notify pgrst,'reload schema';

-- Phase C: fixed-rubric direct-score-v2 handwritten evaluation.
begin;

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','processing_stage2','evaluated','review','failed'
 ));
create unique index if not exists uq_handwritten_submissions_id_tenant
 on public.handwritten_submissions(id,tenant_id);

create table if not exists public.handwritten_evaluations(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 submission_id uuid not null unique,
 status text not null default 'completed' check(status='completed'),
 total_marks_obtained numeric not null check(total_marks_obtained>=0),
 total_marks_possible numeric not null check(total_marks_possible>=0),
 percentage numeric not null check(percentage>=0),
 overall_feedback text not null default '',
 strengths jsonb not null default '[]'::jsonb check(jsonb_typeof(strengths)='array'),
 areas_to_improve jsonb not null default '[]'::jsonb check(jsonb_typeof(areas_to_improve)='array'),
 is_ai_evaluated boolean not null default true check(is_ai_evaluated),
 created_at timestamptz not null default now(),
 constraint handwritten_evaluations_submission_scope_fk
  foreign key(submission_id,tenant_id)
  references public.handwritten_submissions(id,tenant_id) on delete cascade,
 unique(id,tenant_id)
);

create table if not exists public.handwritten_question_evaluations(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 question_ref text not null,
 question_text text not null default '',
 marks_obtained numeric not null check(marks_obtained>=0),
 marks_possible numeric not null check(marks_possible>=0),
 not_attempted boolean not null default false,
 not_evaluated boolean not null default false,
 not_counted boolean not null default false,
 mapping_status text not null check(mapping_status in('matched','recovered','unsafe','blank')),
 feedback text not null default '',
 student_guidance jsonb not null default '{}'::jsonb check(jsonb_typeof(student_guidance)='object'),
 student_answer_excerpt text not null default '',
 handwriting_legibility text not null default 'clear',
 grading_confidence numeric not null default 1 check(grading_confidence between 0 and 1),
 criteria_breakdown jsonb not null default '[]'::jsonb check(jsonb_typeof(criteria_breakdown)='array'),
 created_at timestamptz not null default now(),
 constraint handwritten_question_evaluations_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 unique(evaluation_id,question_ref)
);

create table if not exists public.handwritten_stage2_artifacts(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 sequence integer not null check(sequence>0),
 route text not null check(route in('grouped','whole_paper')),
 model text not null default '',
 prompt_revision text not null default '',
 raw_content text not null default '',
 content_bytes integer not null check(content_bytes>=0),
 content_sha256 text not null check(content_sha256~'^[0-9a-f]{64}$'),
 content_omitted boolean not null default false,
 created_at timestamptz not null default now(),
 constraint handwritten_stage2_artifacts_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 unique(evaluation_id,sequence)
);

create index if not exists handwritten_evaluations_tenant_created
 on public.handwritten_evaluations(tenant_id,created_at desc);
create index if not exists handwritten_question_evaluations_tenant_evaluation
 on public.handwritten_question_evaluations(tenant_id,evaluation_id);
create index if not exists handwritten_stage2_artifacts_tenant_evaluation
 on public.handwritten_stage2_artifacts(tenant_id,evaluation_id,sequence);

alter table public.handwritten_evaluations enable row level security;
alter table public.handwritten_question_evaluations enable row level security;
alter table public.handwritten_stage2_artifacts enable row level security;
revoke all on public.handwritten_evaluations,public.handwritten_question_evaluations,
 public.handwritten_stage2_artifacts from public,anon,authenticated;
grant select,insert,update,delete on public.handwritten_evaluations,
 public.handwritten_question_evaluations,public.handwritten_stage2_artifacts to service_role;

create table if not exists public.ai_provider_slots(
 provider text not null,
 holder_id uuid not null,
 expires_at timestamptz not null,
 created_at timestamptz not null default now(),
 primary key(provider,holder_id)
);
alter table public.ai_provider_slots enable row level security;
revoke all on public.ai_provider_slots from public,anon,authenticated;
grant select,insert,update,delete on public.ai_provider_slots to service_role;
create index if not exists ai_provider_slots_expiry on public.ai_provider_slots(provider,expires_at);

create or replace function public.acquire_ai_provider_slot(
 p_provider text,p_holder uuid,p_limit integer,p_ttl_seconds integer
) returns boolean language plpgsql security invoker set search_path='' as $$
declare active_count integer;
begin
 if p_limit<1 or p_ttl_seconds<1 then return false; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('ai-slot:'||p_provider,0));
 delete from public.ai_provider_slots where provider=p_provider and expires_at<=clock_timestamp();
 if exists(select 1 from public.ai_provider_slots where provider=p_provider and holder_id=p_holder) then
  update public.ai_provider_slots set expires_at=clock_timestamp()+make_interval(secs=>p_ttl_seconds)
   where provider=p_provider and holder_id=p_holder;
  return true;
 end if;
 select count(*) into active_count from public.ai_provider_slots where provider=p_provider;
 if active_count>=p_limit then return false; end if;
 insert into public.ai_provider_slots(provider,holder_id,expires_at)
 values(p_provider,p_holder,clock_timestamp()+make_interval(secs=>p_ttl_seconds));
 return true;
end $$;

create or replace function public.release_ai_provider_slot(p_provider text,p_holder uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 delete from public.ai_provider_slots where provider=p_provider and holder_id=p_holder;
 return found;
end $$;

alter table public.ai_rate_limits drop constraint if exists ai_rate_limits_endpoint_check;
alter table public.ai_rate_limits add constraint ai_rate_limits_endpoint_check check(endpoint in(
 'quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
 'question_explain','quiz_extraction','challenge_join','descriptive_grading',
 'paper_generation','handwritten_evaluation'
));
create or replace function public.consume_ai_rate_limit(
 p_tenant_id uuid,p_user_id uuid,p_endpoint text,p_limit integer
) returns table(allowed boolean,retry_after_seconds integer,remaining integer)
language plpgsql security invoker set search_path='' as $$
declare request_time timestamptz:=clock_timestamp(); consumed_count integer; active_window_start timestamptz;
begin
 if p_limit<1 then raise exception 'Rate limit must be a positive integer'; end if;
 if p_endpoint not in('quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
  'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation',
  'handwritten_evaluation') then raise exception 'Unknown rate-limit endpoint'; end if;
 insert into public.ai_rate_limits as limits(tenant_id,user_id,endpoint,window_started_at,request_count,updated_at)
 values(p_tenant_id,p_user_id,p_endpoint,request_time,1,request_time)
 on conflict(tenant_id,user_id,endpoint) do update set
  window_started_at=case when limits.window_started_at<=request_time-interval '1 hour' then request_time else limits.window_started_at end,
  request_count=case when limits.window_started_at<=request_time-interval '1 hour' then 1 else limits.request_count+1 end,
  updated_at=request_time
 where limits.window_started_at<=request_time-interval '1 hour' or limits.request_count<p_limit
 returning limits.request_count,limits.window_started_at into consumed_count,active_window_start;
 if found then return query select true,0,greatest(p_limit-consumed_count,0); return; end if;
 select limits.window_started_at into active_window_start from public.ai_rate_limits limits
  where limits.tenant_id=p_tenant_id and limits.user_id=p_user_id and limits.endpoint=p_endpoint;
 return query select false,greatest(1,ceil(extract(epoch from(active_window_start+interval '1 hour'-request_time)))::integer),0;
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set status='failed',claimed_by=null,
  lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set status='failed',
  error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j where j.submission_id=s.id
  and j.kind='evaluate_submission' and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing','pending_stage1','processing_stage1',
   'stage1_complete','processing_stage2');
 update public.evaluation_papers p set rubric_status='failed',
  rubric_error='Rubric generation could not finish after repeated interruptions.'
 where exists(select 1 from public.evaluation_jobs j where j.evaluation_paper_id=p.id
  and j.tenant_id=p.tenant_id and j.kind='build_rubric'
  and j.status='failed' and j.attempts>=3)
  and p.rubric_status in('not_started','extracting','generating');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3 order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; current_submission public.handwritten_submissions;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  select s.* into current_submission from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled for update of s;
  if not found then return false; end if;
  update public.handwritten_submissions set
   status=case when current_submission.status in('stage1_complete','processing_stage2')
    then 'processing_stage2' else 'processing_stage1' end,
   error_message=null,updated_at=now() where id=current_submission.id;
 elsif selected.kind='build_rubric' then
  if not exists(select 1 from public.evaluation_papers ep
   join public.profiles p on p.id=ep.created_by and p.tenant_id=ep.tenant_id
   join public.tenants t on t.id=ep.tenant_id
   where ep.id=selected.evaluation_paper_id and ep.tenant_id=selected.tenant_id
    and ep.created_by=selected.owner_teacher_id and ep.is_active and p.role='teacher'
    and t.is_active and t.handwritten_evaluation_enabled and ep.rubric_status<>'ready') then return false; end if;
  update public.evaluation_papers set rubric_status='extracting',rubric_error=''
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
    and created_by=selected.owner_teacher_id;
 else return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now() where id=selected.id;
 return true;
end $$;

create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_extraction)<>'object' or nullif(p_source,'') is null then return false; end if;
 update public.handwritten_submissions set stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
 status=case when p_requires_review then 'review' else 'stage1_complete' end,
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 if not found then return false; end if;
 if p_requires_review then
  update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
   where id=selected.id;
 elsif not exists(select 1 from public.handwritten_submissions s
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and p.rubric_status='ready') then
  update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
   where id=selected.id;
 end if;
 return true;
end $$;

create or replace function public.resume_stage2_on_rubric_ready()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if new.rubric_status='ready' and old.rubric_status is distinct from 'ready' then
  update public.evaluation_jobs j set status='queued',claimed_by=null,
   lease_expires_at=null,attempts=0,updated_at=now()
  from public.handwritten_submissions s
  where s.evaluation_paper_id=new.id and s.tenant_id=new.tenant_id
   and s.status='stage1_complete' and j.submission_id=s.id
   and j.tenant_id=s.tenant_id and j.kind='evaluate_submission' and j.status='done'
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 end if;
 return new;
end $$;
drop trigger if exists resume_stage2_on_rubric_ready on public.evaluation_papers;
create trigger resume_stage2_on_rubric_ready after update of rubric_status
 on public.evaluation_papers for each row execute function public.resume_stage2_on_rubric_ready();

create or replace function public.begin_evaluation_stage2(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 update public.handwritten_submissions s set status='processing_stage2',updated_at=now()
  from public.evaluation_papers p where s.id=selected.submission_id
  and s.tenant_id=selected.tenant_id and s.student_id=selected.owner_student_id
  and p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id and p.rubric_status='ready';
 return found;
end $$;

create or replace function public.finish_evaluation_stage2_job(
 p_id uuid,p_worker uuid,p_evaluation uuid,p_summary jsonb,p_questions jsonb,p_artifacts jsonb,p_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; row jsonb;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_summary)<>'object' or jsonb_typeof(p_questions)<>'array'
  or jsonb_typeof(p_artifacts)<>'array' then return false; end if;
 insert into public.handwritten_evaluations(
  id,tenant_id,submission_id,total_marks_obtained,total_marks_possible,percentage,
  overall_feedback,strengths,areas_to_improve
 ) values(
  p_evaluation,selected.tenant_id,selected.submission_id,
  (p_summary->>'total_marks_obtained')::numeric,(p_summary->>'total_marks_possible')::numeric,
  (p_summary->>'percentage')::numeric,coalesce(p_summary->>'overall_feedback',''),
  coalesce(p_summary->'strengths','[]'::jsonb),coalesce(p_summary->'areas_to_improve','[]'::jsonb)
 );
 for row in select value from jsonb_array_elements(p_questions) loop
  insert into public.handwritten_question_evaluations(
   tenant_id,evaluation_id,question_ref,question_text,marks_obtained,marks_possible,
   not_attempted,not_evaluated,not_counted,mapping_status,feedback,student_guidance,
   student_answer_excerpt,handwriting_legibility,grading_confidence,criteria_breakdown
  ) values(selected.tenant_id,p_evaluation,row->>'question_ref',coalesce(row->>'question_text',''),
   (row->>'marks_obtained')::numeric,(row->>'marks_possible')::numeric,
   coalesce((row->>'not_attempted')::boolean,false),coalesce((row->>'not_evaluated')::boolean,false),
   coalesce((row->>'not_counted')::boolean,false),row->>'mapping_status',coalesce(row->>'feedback',''),
   coalesce(row->'student_guidance','{}'::jsonb),coalesce(row->>'student_answer_excerpt',''),
   coalesce(row->>'handwriting_legibility','clear'),coalesce((row->>'grading_confidence')::numeric,1),
   coalesce(row->'criteria_breakdown','[]'::jsonb));
 end loop;
 for row in select value from jsonb_array_elements(p_artifacts) loop
  insert into public.handwritten_stage2_artifacts(
   tenant_id,evaluation_id,sequence,route,model,prompt_revision,raw_content,
   content_bytes,content_sha256,content_omitted
  ) values(selected.tenant_id,p_evaluation,(row->>'sequence')::integer,row->>'route',
   coalesce(row->>'model',''),coalesce(row->>'prompt_revision',''),coalesce(row->>'raw_content',''),
   (row->>'content_bytes')::integer,row->>'content_sha256',coalesce((row->>'content_omitted')::boolean,false));
 end loop;
 update public.handwritten_submissions set status=case when p_review then 'review' else 'evaluated' end,
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_job(p_id uuid,p_worker uuid,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status in('claimed','processing') and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
  into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying and has_stage1 then 'stage1_complete' when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation processing failed.' end,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 return true;
end $$;

update public.evaluation_jobs j set status='queued',claimed_by=null,lease_expires_at=null,updated_at=now()
from public.handwritten_submissions s where j.submission_id=s.id and j.kind='evaluate_submission'
 and j.status='done' and s.status='stage1_complete'
 and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);

revoke all on function public.acquire_ai_provider_slot(text,uuid,integer,integer),
 public.release_ai_provider_slot(text,uuid),public.begin_evaluation_stage2(uuid,uuid),
 public.finish_evaluation_stage2_job(uuid,uuid,uuid,jsonb,jsonb,jsonb,boolean),
 public.resume_stage2_on_rubric_ready()
 from public,anon,authenticated;
grant execute on function public.acquire_ai_provider_slot(text,uuid,integer,integer),
 public.release_ai_provider_slot(text,uuid),public.begin_evaluation_stage2(uuid,uuid),
 public.finish_evaluation_stage2_job(uuid,uuid,uuid,jsonb,jsonb,jsonb,boolean)
 to service_role;

commit;
notify pgrst,'reload schema';
-- Phase D: mistake library, revision reconciliation, and student analytics.
begin;

create unique index if not exists uq_handwritten_question_evaluations_id_tenant
 on public.handwritten_question_evaluations(id,tenant_id);

create table if not exists public.handwritten_mistakes(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 question_result_id uuid,
 category text not null check(category in(
  'not_attempted','conceptual','application','presentation','calculation',
  'step_loss','keyword','format','time_management'
 )),
 severity text not null check(severity in('minor','moderate','major')),
 description text not null,
 marks_lost numeric not null check(marks_lost>0),
 suggestion text not null default '',
 chapter_name text not null,
 criterion_key text not null check(char_length(criterion_key) between 1 and 120),
 signature text not null check(signature~'^[0-9a-f]{64}$'),
 is_recurring boolean not null default false,
 created_at timestamptz not null default now(),
 constraint handwritten_mistakes_evaluation_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 constraint handwritten_mistakes_question_scope_fk
  foreign key(question_result_id,tenant_id)
  references public.handwritten_question_evaluations(id,tenant_id) on delete cascade
);

create table if not exists public.handwritten_revision_items(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 subject_id uuid not null,
 chapter text not null,
 title text not null,
 description text not null default '',
 priority text not null check(priority in('high','medium','low')),
 is_resolved boolean not null default false,
 occurrence_count integer not null default 0 check(occurrence_count>=0),
 marks_at_risk numeric not null default 0 check(marks_at_risk>=0),
 source_count integer not null default 0 check(source_count>=0),
 resolution_source text not null default '' check(resolution_source in('','reviewed','improved')),
 resolved_at timestamptz,
 last_seen_at timestamptz not null default now(),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint handwritten_revision_items_student_scope_fk
  foreign key(student_id,tenant_id) references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_revision_items_subject_scope_fk
  foreign key(subject_id,tenant_id) references public.subjects(id,tenant_id) on delete cascade,
 unique(tenant_id,student_id,subject_id,title)
);

create table if not exists public.handwritten_student_analytics(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 subject_id uuid not null,
 total_attempts integer not null default 0 check(total_attempts>=0),
 avg_percentage numeric not null default 0,
 best_percentage numeric not null default 0,
 latest_percentage numeric not null default 0,
 score_history jsonb not null default '[]'::jsonb check(jsonb_typeof(score_history)='array'),
 current_level text not null default 'beginner' check(current_level in(
  'beginner','improving','proficient','advanced','exam_ready'
 )),
 improvement_rate numeric not null default 0,
 updated_at timestamptz not null default now(),
 constraint handwritten_student_analytics_student_scope_fk
  foreign key(student_id,tenant_id) references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_student_analytics_subject_scope_fk
  foreign key(subject_id,tenant_id) references public.subjects(id,tenant_id) on delete cascade,
 unique(tenant_id,student_id,subject_id)
);

create index if not exists handwritten_mistakes_evaluation
 on public.handwritten_mistakes(tenant_id,evaluation_id);
create index if not exists handwritten_mistakes_signature
 on public.handwritten_mistakes(tenant_id,signature,is_recurring);
create index if not exists handwritten_revision_items_student_subject
 on public.handwritten_revision_items(tenant_id,student_id,subject_id,is_resolved);
create index if not exists handwritten_student_analytics_student
 on public.handwritten_student_analytics(tenant_id,student_id,updated_at desc);

alter table public.handwritten_mistakes enable row level security;
alter table public.handwritten_revision_items enable row level security;
alter table public.handwritten_student_analytics enable row level security;
revoke all on public.handwritten_mistakes,public.handwritten_revision_items,
 public.handwritten_student_analytics from public,anon,authenticated;
grant select,insert,update,delete on public.handwritten_mistakes,
 public.handwritten_revision_items,public.handwritten_student_analytics to service_role;

create or replace function public.replace_handwritten_mistakes(
 p_tenant uuid,p_evaluation uuid,p_rows jsonb
) returns integer language plpgsql security invoker set search_path='' as $$
declare item jsonb; inserted integer:=0;
begin
 if jsonb_typeof(p_rows)<>'array' then raise exception 'mistake rows must be an array'; end if;
 if not exists(
  select 1 from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where e.id=p_evaluation and e.tenant_id=p_tenant and e.status='completed'
   and s.status='evaluated'
 ) then raise exception 'evaluation is not committed for learning'; end if;
 delete from public.handwritten_mistakes where tenant_id=p_tenant and evaluation_id=p_evaluation;
 for item in select value from jsonb_array_elements(p_rows) loop
  if nullif(item->>'question_result_id','') is not null and not exists(
   select 1 from public.handwritten_question_evaluations q
   where q.id=(item->>'question_result_id')::uuid and q.tenant_id=p_tenant
    and q.evaluation_id=p_evaluation
  ) then raise exception 'question result is outside evaluation scope'; end if;
  insert into public.handwritten_mistakes(
   tenant_id,evaluation_id,question_result_id,category,severity,description,
   marks_lost,suggestion,chapter_name,criterion_key,signature
  ) values(
   p_tenant,p_evaluation,nullif(item->>'question_result_id','')::uuid,
   item->>'category',item->>'severity',item->>'description',
   (item->>'marks_lost')::numeric,coalesce(item->>'suggestion',''),
   item->>'chapter_name',item->>'criterion_key',item->>'signature'
  );
  inserted:=inserted+1;
 end loop;
 return inserted;
end $$;

create or replace function public.reconcile_handwritten_revision_items(
 p_tenant uuid,p_student uuid,p_subject uuid
) returns boolean language plpgsql security invoker set search_path='' as $$
declare topic_row record; reconciled_at timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.profiles p where p.id=p_student
  and p.tenant_id=p_tenant and p.role='student' for update) then return false; end if;
 if not exists(select 1 from public.subjects s where s.id=p_subject and s.tenant_id=p_tenant) then return false; end if;

 update public.handwritten_mistakes m set is_recurring=false
 where m.tenant_id=p_tenant and exists(
  select 1 from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.id=m.evaluation_id and hs.student_id=p_student and ep.subject_id=p_subject
 );

 with ranked as(
  select e.id evaluation_id,hs.evaluation_paper_id,
   row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
  from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
   and e.status='completed' and hs.status='evaluated'
 ), recurring as(
  select m.signature
  from public.handwritten_mistakes m join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.signature<>''
  group by m.signature having count(distinct r.evaluation_paper_id)>=2
 )
 update public.handwritten_mistakes m set is_recurring=true
 from ranked r,recurring x where r.position=1 and m.evaluation_id=r.evaluation_id
  and m.tenant_id=p_tenant and m.signature=x.signature;

 for topic_row in
  with ranked as(
   select e.id evaluation_id,hs.evaluation_paper_id,
    row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
   from public.handwritten_evaluations e
   join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
   join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
   where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
    and e.status='completed' and hs.status='evaluated'
  )
  select m.chapter_name,round(sum(m.marks_lost),1) marks,
   count(distinct r.evaluation_paper_id)::integer paper_count,
   (array_agg(coalesce(nullif(m.suggestion,''),m.description)
    order by m.marks_lost desc,m.created_at desc))[1] description
  from public.handwritten_mistakes m join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.chapter_name<>''
  group by m.chapter_name
 loop
  insert into public.handwritten_revision_items(
   tenant_id,student_id,subject_id,chapter,title,description,priority,
   is_resolved,occurrence_count,marks_at_risk,source_count,resolution_source,
   resolved_at,last_seen_at,updated_at
  ) values(
   p_tenant,p_student,p_subject,topic_row.chapter_name,left(topic_row.chapter_name,300),
   left(coalesce(topic_row.description,''),1000),
   case when topic_row.marks>=3 or topic_row.paper_count>=3 then 'high'
    when topic_row.marks>=1 or topic_row.paper_count>=2 then 'medium' else 'low' end,
   false,topic_row.paper_count,topic_row.marks,topic_row.paper_count,'',null,reconciled_at,reconciled_at
  ) on conflict(tenant_id,student_id,subject_id,title) do update set
   chapter=excluded.chapter,description=excluded.description,priority=excluded.priority,
   is_resolved=false,occurrence_count=excluded.occurrence_count,
   marks_at_risk=excluded.marks_at_risk,source_count=excluded.source_count,
   resolution_source='',resolved_at=null,last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at;
 end loop;

 with ranked as(
  select e.id evaluation_id,hs.evaluation_paper_id,
   row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
  from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
   and e.status='completed' and hs.status='evaluated'
 ), desired as(
  select distinct m.chapter_name from public.handwritten_mistakes m
  join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.chapter_name<>''
 )
 update public.handwritten_revision_items ri set is_resolved=true,
  resolution_source='improved',resolved_at=reconciled_at,marks_at_risk=0,updated_at=reconciled_at
 where ri.tenant_id=p_tenant and ri.student_id=p_student and ri.subject_id=p_subject
  and not ri.is_resolved and not exists(select 1 from desired d where left(d.chapter_name,300)=ri.title);
 return true;
end $$;

revoke all on function public.replace_handwritten_mistakes(uuid,uuid,jsonb),
 public.reconcile_handwritten_revision_items(uuid,uuid,uuid)
 from public,anon,authenticated;
grant execute on function public.replace_handwritten_mistakes(uuid,uuid,jsonb),
 public.reconcile_handwritten_revision_items(uuid,uuid,uuid) to service_role;

commit;
notify pgrst,'reload schema';
-- Link AI-call telemetry to handwritten evaluation jobs without reusing the
-- quiz_generation_jobs foreign key.
begin;

alter table public.api_call_logs
 add column if not exists evaluation_job_id uuid;

alter table public.api_call_logs
 drop constraint if exists api_call_logs_evaluation_job_id_fkey;
alter table public.api_call_logs
 add constraint api_call_logs_evaluation_job_id_fkey
 foreign key(evaluation_job_id) references public.evaluation_jobs(id) on delete set null;

create index if not exists api_call_logs_evaluation_job_time
 on public.api_call_logs(evaluation_job_id,created_at desc);

commit;
notify pgrst,'reload schema';
-- Handwritten evaluation hardening: bounded retries, recovery, history safety,
-- re-evaluation plumbing, and descriptive-section marks.
begin;

alter table public.evaluation_papers
 add column if not exists mcq_marks numeric;
alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_mcq_marks_check;
alter table public.evaluation_papers
 add constraint evaluation_papers_mcq_marks_check check(
  mcq_marks is null or (mcq_marks>=0 and mcq_marks<=total_marks)
 );

alter table public.handwritten_submissions
 add column if not exists paper_title_snapshot text,
 add column if not exists subject_name_snapshot text;
update public.handwritten_submissions s set
 paper_title_snapshot=coalesce(s.paper_title_snapshot,p.title,'Deleted evaluation paper'),
 subject_name_snapshot=coalesce(s.subject_name_snapshot,sub.name,'Deleted subject')
from public.evaluation_papers p
left join public.subjects sub on sub.id=p.subject_id and sub.tenant_id=p.tenant_id
where s.evaluation_paper_id=p.id and s.tenant_id=p.tenant_id
 and (s.paper_title_snapshot is null or s.subject_name_snapshot is null);
update public.handwritten_submissions set
 paper_title_snapshot=coalesce(paper_title_snapshot,'Deleted evaluation paper'),
 subject_name_snapshot=coalesce(subject_name_snapshot,'Deleted subject');
alter table public.handwritten_submissions
 alter column paper_title_snapshot set not null,
 alter column subject_name_snapshot set not null,
 alter column upload_intent_id drop not null,
 alter column evaluation_paper_id drop not null;
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_answer_script_path_key;
create index if not exists handwritten_submissions_answer_script_path
 on public.handwritten_submissions(answer_script_path);

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','processing_stage2','evaluated','review','failed',
  'blocked_rubric_failed'
 ));

create unique index if not exists uq_evaluation_intents_owner_scope
 on public.evaluation_upload_intents(id,tenant_id,student_id);
alter table public.evaluation_upload_intents
 add column if not exists purpose text not null default 'primary',
 add column if not exists submission_id uuid,
 alter column evaluation_paper_id drop not null;
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_upload_intents_purpose_check;
alter table public.evaluation_upload_intents
 add constraint evaluation_upload_intents_purpose_check check(
  purpose in('primary','additional_pages')
 );
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_paper_tenant_fk;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id)
  on delete set null(evaluation_paper_id);
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_submission_scope_fk;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_submission_scope_fk
  foreign key(submission_id,tenant_id,student_id)
  references public.handwritten_submissions(id,tenant_id,student_id)
  on delete cascade;
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_target_check;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_target_check check(
  (purpose='primary' and submission_id is null)
  or (purpose='additional_pages' and submission_id is not null)
 );

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_intent_scope_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_intent_scope_fk
  foreign key(upload_intent_id,tenant_id,student_id)
  references public.evaluation_upload_intents(id,tenant_id,student_id)
  on delete restrict;
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_paper_tenant_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id)
  on delete set null(evaluation_paper_id);

alter table public.evaluation_jobs
 add column if not exists available_at timestamptz not null default now(),
 add column if not exists processing_started_at timestamptz,
 add column if not exists last_failure_reason text;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_attempts_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_attempts_check check(attempts between 0 and 4);
drop index if exists public.evaluation_jobs_queue;
create index evaluation_jobs_queue
 on public.evaluation_jobs(status,available_at,created_at)
 where status in('queued','claimed','processing');

create or replace function public.evaluation_retry_delay(p_attempts integer)
returns interval language sql immutable security invoker set search_path='' as $$
 select case
  when p_attempts<=1 then interval '30 seconds'
  when p_attempts=2 then interval '60 seconds'
  else interval '120 seconds'
 end
$$;

create or replace function public.create_limited_handwritten_submission_job(
 p_tenant uuid,p_student uuid,p_intent uuid,p_limit integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents;
 submission public.handwritten_submissions;
 job public.evaluation_jobs;
 paper public.evaluation_papers;
 subject_name text;
 completed integer;
 active integer;
begin
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 if p_limit<1 then raise exception 'evaluation_attempt_limit_invalid'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
  p_tenant::text||':'||p_student::text||':'||intent.evaluation_paper_id::text,0
 ));
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 if intent.purpose<>'primary' then
  raise exception 'evaluation_intent_wrong_purpose' using errcode='PT409';
 end if;
 select * into submission from public.handwritten_submissions
  where upload_intent_id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if found then
  select * into job from public.evaluation_jobs where submission_id=submission.id;
  return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
 end if;
 if intent.status<>'verified' or intent.expires_at<=now() then
  raise exception 'evaluation_intent_not_verified' using errcode='PT409';
 end if;
 select count(*) into completed from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=intent.evaluation_paper_id;
 select count(distinct s.id) into active from public.handwritten_submissions s
  join public.evaluation_jobs j on j.submission_id=s.id and j.tenant_id=s.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=intent.evaluation_paper_id
   and j.status in('queued','claimed','processing')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 if completed>=p_limit or completed+active>=p_limit then
  raise exception 'evaluation_attempt_limit_reached' using errcode='PT409';
 end if;
 select ep.* into paper from public.evaluation_papers ep
  join public.subjects s on s.id=ep.subject_id and s.tenant_id=ep.tenant_id
  join public.enrollments e on e.tenant_id=ep.tenant_id
   and e.profile_id=p_student and e.course_id=s.course_id
   and e.course_level_id=ep.course_level_id
  where ep.id=intent.evaluation_paper_id and ep.tenant_id=p_tenant and ep.is_active;
 if not found or not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
   where p.id=p_student and p.tenant_id=p_tenant and p.role='student' and t.is_active
 ) then raise exception 'evaluation_access_denied' using errcode='PT403'; end if;
 select s.name into subject_name from public.subjects s
  where s.id=paper.subject_id and s.tenant_id=paper.tenant_id;
 insert into public.handwritten_submissions(
  tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,
  paper_title_snapshot,subject_name_snapshot,status
 ) values(
  p_tenant,p_student,paper.id,intent.id,intent.storage_path,
  paper.title,coalesce(subject_name,'Deleted subject'),'queued'
 ) returning * into submission;
 update public.evaluation_upload_intents set status='consumed'
  where id=intent.id and tenant_id=p_tenant and student_id=p_student;
 insert into public.evaluation_jobs(
  tenant_id,submission_id,owner_student_id,available_at
 ) values(p_tenant,submission.id,p_student,now()) returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 perform public.reap_stuck_evaluation_jobs(780);
 select * into selected from public.evaluation_jobs j
  where j.status='queued' and j.available_at<=clock_timestamp() and j.attempts<4
  order by j.available_at,j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,
  claimed_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '120 seconds',
  attempts=attempts+1,processing_started_at=null,last_failure_reason=null,updated_at=clock_timestamp()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; current_submission public.handwritten_submissions;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  select s.* into current_submission from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled for update of s;
  if not found or current_submission.evaluation_paper_id is null then return false; end if;
  update public.handwritten_submissions set
   status=case when current_submission.status in('stage1_complete','processing_stage2')
    then 'processing_stage2' else 'processing_stage1' end,
   error_message=null,updated_at=clock_timestamp() where id=current_submission.id;
 elsif selected.kind='build_rubric' then
  if not exists(select 1 from public.evaluation_papers ep
   join public.profiles p on p.id=ep.created_by and p.tenant_id=ep.tenant_id
   join public.tenants t on t.id=ep.tenant_id
   where ep.id=selected.evaluation_paper_id and ep.tenant_id=selected.tenant_id
    and ep.created_by=selected.owner_teacher_id and ep.is_active and p.role='teacher'
    and t.is_active and t.handwritten_evaluation_enabled and ep.rubric_status<>'ready') then return false; end if;
  update public.evaluation_papers set rubric_status='extracting',rubric_error=''
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
    and created_by=selected.owner_teacher_id;
 else return false; end if;
 update public.evaluation_jobs set status='processing',processing_started_at=clock_timestamp(),
  updated_at=clock_timestamp() where id=selected.id;
 return true;
end $$;

create or replace function public.timeout_evaluation_job(
 p_id uuid,p_worker uuid,p_reason text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; delay interval; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status in('claimed','processing') and claimed_by=p_worker for update;
 if not found then return jsonb_build_object('changed',false); end if;
 retrying:=selected.attempts<4;
 delay:=public.evaluation_retry_delay(selected.attempts);
 update public.evaluation_jobs set
  status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+delay else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason=left(coalesce(nullif(trim(p_reason),''),'Evaluation processing timed out.'),2000),
  updated_at=clock_timestamp() where id=selected.id;
 if selected.kind='evaluate_submission' then
  select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
   into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
  update public.handwritten_submissions set
   status=case when retrying and has_stage1 then 'stage1_complete'
    when retrying then 'queued' else 'failed' end,
   error_message=case when retrying then null else left(coalesce(p_reason,'Evaluation processing timed out.'),2000) end,
   updated_at=clock_timestamp() where id=selected.submission_id and tenant_id=selected.tenant_id;
 else
  update public.evaluation_papers set
   rubric_status=case when retrying then 'not_started' else 'failed' end,
   rubric_error=case when retrying then '' else left(coalesce(p_reason,'Rubric generation timed out.'),2000) end
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id;
 end if;
 return jsonb_build_object('changed',true,'retrying',retrying,
  'available_at',case when retrying then clock_timestamp()+delay else null end);
end $$;

create or replace function public.reap_stuck_evaluation_jobs(p_soft_timeout_seconds integer default 780)
returns integer language plpgsql security invoker set search_path='' as $$
declare stale record; reaped integer:=0; worker uuid;
begin
 if p_soft_timeout_seconds<1 then raise exception 'soft timeout must be positive'; end if;
 for stale in
  select id,claimed_by from public.evaluation_jobs
  where status in('claimed','processing') and claimed_by is not null and (
   lease_expires_at<=clock_timestamp()
   or coalesce(processing_started_at,claimed_at,updated_at)
      <=clock_timestamp()-make_interval(secs=>p_soft_timeout_seconds)
  ) order by updated_at for update skip locked
 loop
  worker:=stale.claimed_by;
  perform public.timeout_evaluation_job(stale.id,worker,'Evaluation processing exceeded its safe duration.');
  reaped:=reaped+1;
 end loop;
 return reaped;
end $$;

create or replace function public.fail_evaluation_job(p_id uuid,p_worker uuid,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status in('claimed','processing') and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<4;
 select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
  into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+public.evaluation_retry_delay(selected.attempts) else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason='Evaluation processing failed.',updated_at=clock_timestamp() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying and has_stage1 then 'stage1_complete' when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation processing failed.' end,updated_at=clock_timestamp()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 return true;
end $$;

create or replace function public.fail_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_retryable boolean,p_error text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status in('claimed','processing')
  and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<4;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+public.evaluation_retry_delay(selected.attempts) else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason=left(coalesce(p_error,'Rubric generation failed.'),2000),updated_at=clock_timestamp()
  where id=selected.id;
 update public.evaluation_papers set
  rubric_status=case when retrying then 'not_started' else 'failed' end,
  rubric_error=case when retrying then '' else left(coalesce(p_error,'Rubric generation failed.'),2000) end
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 if not retrying then
  update public.handwritten_submissions set status='blocked_rubric_failed',
   error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
   updated_at=clock_timestamp()
   where evaluation_paper_id=selected.evaluation_paper_id
    and tenant_id=selected.tenant_id and status='stage1_complete'
    and not exists(select 1 from public.handwritten_evaluations e
     where e.submission_id=handwritten_submissions.id);
 end if;
 return true;
end $$;

create or replace function public.block_submission_for_failed_rubric(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select j.* into selected from public.evaluation_jobs j
  join public.handwritten_submissions s on s.id=j.submission_id and s.tenant_id=j.tenant_id
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where j.id=p_id and j.kind='evaluate_submission' and j.status='processing'
   and j.claimed_by=p_worker and j.lease_expires_at>clock_timestamp()
   and p.rubric_status='failed' for update of j,s;
 if not found then return false; end if;
 update public.handwritten_submissions set status='blocked_rubric_failed',
  error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
  updated_at=clock_timestamp() where id=selected.submission_id and tenant_id=selected.tenant_id;
 update public.evaluation_jobs set status='done',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,updated_at=clock_timestamp() where id=selected.id;
 return true;
end $$;

create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; rubric text;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found or jsonb_typeof(p_extraction)<>'object' or nullif(p_source,'') is null then return false; end if;
 select p.rubric_status into rubric from public.handwritten_submissions s
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id;
 update public.handwritten_submissions set stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
  status=case when p_requires_review then 'review'
   when rubric='failed' then 'blocked_rubric_failed' else 'stage1_complete' end,
  error_message=case when rubric='failed' then
   'Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.'
   else null end,updated_at=clock_timestamp()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 if not found then return false; end if;
 if p_requires_review or rubric is distinct from 'ready' then
  update public.evaluation_jobs set status='done',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,updated_at=clock_timestamp() where id=selected.id;
 end if;
 return true;
end $$;

create or replace function public.resume_stage2_on_rubric_ready()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if new.rubric_status='ready' and old.rubric_status is distinct from 'ready' then
  update public.evaluation_jobs j set status='queued',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
   last_failure_reason=null,updated_at=clock_timestamp()
  from public.handwritten_submissions s
  where s.evaluation_paper_id=new.id and s.tenant_id=new.tenant_id
   and s.status in('stage1_complete','blocked_rubric_failed')
   and j.submission_id=s.id and j.tenant_id=s.tenant_id
   and j.kind='evaluate_submission' and j.status in('done','failed')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
  update public.handwritten_submissions set status='stage1_complete',error_message=null,
   updated_at=clock_timestamp() where evaluation_paper_id=new.id and tenant_id=new.tenant_id
   and status='blocked_rubric_failed'
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=handwritten_submissions.id);
 end if;
 return new;
end $$;

create or replace function public.reset_evaluation_rubric(p_tenant uuid,p_paper uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 update public.evaluation_papers set structured_qa='{}'::jsonb,question_structure=null,
  rubric_source=null,rubric_error='',question_paper_text=null,suggested_answer_text=null,
  rubric_status='not_started' where id=p_paper and tenant_id=p_tenant;
 if not found then return false; end if;
 update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
  last_failure_reason=null,updated_at=clock_timestamp()
  where evaluation_paper_id=p_paper and tenant_id=p_tenant and kind='build_rubric';
 return found;
end $$;

create or replace function public.attach_handwritten_additional_pages(
 p_tenant uuid,p_student uuid,p_submission uuid,p_intent uuid
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents; submission public.handwritten_submissions; job public.evaluation_jobs;
begin
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_submission::text,0));
 select * into submission from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if exists(select 1 from public.handwritten_evaluations where submission_id=submission.id) then
  raise exception 'completed_submission_is_immutable' using errcode='PT409';
 end if;
 select * into intent from public.evaluation_upload_intents where id=p_intent
  and tenant_id=p_tenant and student_id=p_student and submission_id=p_submission
  and purpose='additional_pages' for update;
 if not found or intent.status<>'verified' or intent.expires_at<=clock_timestamp() then
  raise exception 'additional_pages_intent_not_verified' using errcode='PT409';
 end if;
 update public.handwritten_submissions set additional_pages_path=intent.storage_path,
  stage1_extraction='{}'::jsonb,stage1_extraction_source=null,page_mapping=null,
  status='queued',error_message=null,retrigger_count=retrigger_count+1,
  updated_at=clock_timestamp() where id=submission.id returning * into submission;
 update public.evaluation_upload_intents set status='consumed' where id=intent.id;
 update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
  last_failure_reason=null,updated_at=clock_timestamp()
  where submission_id=submission.id returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.retrigger_handwritten_submission(
 p_tenant uuid,p_student uuid,p_submission uuid,p_limit integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare original public.handwritten_submissions; next_submission public.handwritten_submissions;
 job public.evaluation_jobs; completed integer; active integer;
begin
 if p_limit<1 then raise exception 'evaluation_attempt_limit_invalid'; end if;
 select * into original from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if original.evaluation_paper_id is null then
  raise exception 'evaluation_paper_deleted' using errcode='PT409';
 end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
  p_tenant::text||':'||p_student::text||':'||original.evaluation_paper_id::text,0
 ));
 select * into original from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if original.evaluation_paper_id is null then
  raise exception 'evaluation_paper_deleted' using errcode='PT409';
 end if;
 select count(*) into completed from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=original.evaluation_paper_id;
 if completed>=p_limit then raise exception 'evaluation_attempt_limit_reached' using errcode='PT409'; end if;
 if exists(select 1 from public.evaluation_jobs j where j.submission_id=original.id
  and j.status in('queued','claimed','processing')) then
  raise exception 'evaluation_already_active' using errcode='PT409';
 end if;
 select count(distinct s.id) into active from public.handwritten_submissions s
  join public.evaluation_jobs j on j.submission_id=s.id and j.tenant_id=s.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=original.evaluation_paper_id and s.id<>original.id
   and j.status in('queued','claimed','processing')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 if completed+active>=p_limit then
  raise exception 'evaluation_attempt_limit_reached' using errcode='PT409';
 end if;
 if exists(select 1 from public.handwritten_evaluations where submission_id=original.id) then
  if exists(select 1 from public.handwritten_submissions s join public.evaluation_jobs j on j.submission_id=s.id
   where s.regraded_from=original.id and s.tenant_id=p_tenant and s.student_id=p_student
    and j.status in('queued','claimed','processing')) then
   raise exception 'evaluation_already_active' using errcode='PT409';
  end if;
  insert into public.handwritten_submissions(
   tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,
   additional_pages_path,status,retrigger_count,regraded_from,paper_title_snapshot,
   subject_name_snapshot,stage1_extraction,stage1_extraction_source,page_mapping
  ) values(
   original.tenant_id,original.student_id,original.evaluation_paper_id,null,
   original.answer_script_path,original.additional_pages_path,'queued',original.retrigger_count+1,
   original.id,original.paper_title_snapshot,original.subject_name_snapshot,
   original.stage1_extraction,original.stage1_extraction_source,original.page_mapping
  ) returning * into next_submission;
  insert into public.evaluation_jobs(tenant_id,submission_id,owner_student_id,available_at)
   values(p_tenant,next_submission.id,p_student,clock_timestamp()) returning * into job;
 else
  if original.status not in('failed','blocked_rubric_failed','stage1_complete','review') then
   raise exception 'submission_cannot_be_retriggered' using errcode='PT409';
  end if;
  update public.handwritten_submissions set status=case
   when jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb then 'stage1_complete'
   else 'queued' end,error_message=null,retrigger_count=retrigger_count+1,updated_at=clock_timestamp()
   where id=original.id returning * into next_submission;
  update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
   last_failure_reason=null,updated_at=clock_timestamp()
   where submission_id=original.id returning * into job;
 end if;
 return jsonb_build_object('submission',to_jsonb(next_submission),'job',to_jsonb(job),
  'completed_attempts',completed,'attempt_limit',p_limit);
end $$;

create or replace function public.mark_handwritten_submission_failed(
 p_tenant uuid,p_submission uuid,p_reason text
) returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if nullif(trim(p_reason),'') is null then raise exception 'failure_reason_required'; end if;
 update public.handwritten_submissions set status='failed',error_message=left(trim(p_reason),2000),
  updated_at=clock_timestamp() where id=p_submission and tenant_id=p_tenant
  and status not in('evaluated','review');
 if not found then return false; end if;
 update public.evaluation_jobs set status='failed',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,last_failure_reason=left(trim(p_reason),2000),
  updated_at=clock_timestamp() where submission_id=p_submission and tenant_id=p_tenant;
 return true;
end $$;

update public.handwritten_submissions s set status='blocked_rubric_failed',
 error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
 updated_at=clock_timestamp()
from public.evaluation_papers p
where s.evaluation_paper_id=p.id and s.tenant_id=p.tenant_id
 and s.status='stage1_complete' and p.rubric_status='failed'
 and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);

revoke all on function public.evaluation_retry_delay(integer),
 public.create_limited_handwritten_submission_job(uuid,uuid,uuid,integer),
 public.timeout_evaluation_job(uuid,uuid,text),public.reap_stuck_evaluation_jobs(integer),
 public.block_submission_for_failed_rubric(uuid,uuid),public.reset_evaluation_rubric(uuid,uuid),
 public.attach_handwritten_additional_pages(uuid,uuid,uuid,uuid),
 public.retrigger_handwritten_submission(uuid,uuid,uuid,integer),
 public.mark_handwritten_submission_failed(uuid,uuid,text)
 from public,anon,authenticated;
grant execute on function public.evaluation_retry_delay(integer),
 public.create_limited_handwritten_submission_job(uuid,uuid,uuid,integer),
 public.timeout_evaluation_job(uuid,uuid,text),public.reap_stuck_evaluation_jobs(integer),
 public.block_submission_for_failed_rubric(uuid,uuid),public.reset_evaluation_rubric(uuid,uuid),
 public.attach_handwritten_additional_pages(uuid,uuid,uuid,uuid),
 public.retrigger_handwritten_submission(uuid,uuid,uuid,integer),
 public.mark_handwritten_submission_failed(uuid,uuid,text)
 to service_role;

commit;
notify pgrst,'reload schema';
