-- ============================================================================
-- Migration 32 — Reset & recreate the chunked-generation tables
-- Run this ONCE in the Supabase SQL Editor.
--
-- WHY THIS EXISTS
--   An earlier draft of migration-24 created `quiz_generation_jobs` /
--   `document_chunks` with a different shape (e.g. no `phase` column). Because
--   migration-31 uses `create table IF NOT EXISTS`, re-running it does NOT add
--   the new columns to the already-existing tables — so inserts fail with
--   "Could not find the 'phase' column".
--
-- SAFE TO DROP
--   Both tables hold ONLY transient generation state — chunks + in-flight
--   analysis jobs + the consolidated blueprint. Nothing here is shown to
--   students or used in analytics; the finished quiz is a normal quiz_set /
--   variant / questions created by existing code. So dropping + recreating them
--   loses no real data. (Any in-progress large-doc analysis would just need to
--   be re-run — simply click "Extract topics" again.)
--
--   This migration is fully re-runnable: it drops first, and drops each policy
--   before creating it. It supersedes the table/enum/RLS section of
--   migration-31 — you do NOT need to run migration-31 again after this.
-- ============================================================================

-- 1) Drop the transient tables (cascade removes their policies + indexes) and
--    the enum, so we can recreate everything to match the current backend.
drop table if exists public.document_chunks      cascade;
drop table if exists public.quiz_generation_jobs cascade;
drop type  if exists generation_job_status;

-- 2) Recreate the job-level status enum (chunks reuse the existing `job_status`).
do $$ begin
  create type generation_job_status as enum
    ('queued', 'running', 'partial', 'completed', 'failed');
exception when duplicate_object then null;
end $$;

-- 3) One row per chunk of a document: the text, its content hash (for exact
--    de-duplication within the document), and its MAP output + status.
create table if not exists public.document_chunks (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references public.tenants(id),
  document_id   uuid not null references public.documents(id) on delete cascade,
  chunk_index   int  not null,
  content       text not null,
  content_hash  text not null,                 -- SHA-256 of `content`
  char_start    int,
  char_end      int,
  topics_json   jsonb,                          -- MAP result (null until extracted)
  map_status    job_status not null default 'queued',  -- queued/running/succeeded/failed
  attempts      int not null default 0,
  error_message text,
  updated_at    timestamptz not null default now(),
  unique (document_id, chunk_index),
  unique (document_id, content_hash)            -- skip byte-identical chunks in a doc
);
create index if not exists idx_docchunks_document on public.document_chunks(document_id);
create index if not exists idx_docchunks_tenant   on public.document_chunks(tenant_id);
create index if not exists idx_docchunks_mapstatus on public.document_chunks(document_id, map_status);

-- 4) One row per large-document analysis run: phase/status + the consolidated
--    Master Blueprint produced by the REDUCE step.
create table if not exists public.quiz_generation_jobs (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references public.tenants(id),
  created_by      uuid not null references public.profiles(id) on delete cascade,
  document_id     uuid not null references public.documents(id) on delete cascade,
  subject_id      uuid references public.subjects(id),
  chapter_name    text,
  params          jsonb not null default '{}'::jsonb,   -- chunking + request params
  master_blueprint jsonb,                               -- REDUCE result (null until ready)
  status          generation_job_status not null default 'queued',
  phase           text not null default 'queued',       -- chunking | mapping | reducing | ready
  total_chunks    int not null default 0,
  done_chunks     int not null default 0,
  quiz_set_id     uuid references public.quiz_sets(id) on delete set null,
  error_message   text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_genjobs_tenant   on public.quiz_generation_jobs(tenant_id);
create index if not exists idx_genjobs_document  on public.quiz_generation_jobs(document_id);
create index if not exists idx_genjobs_status    on public.quiz_generation_jobs(status);

-- 5) Row Level Security (mirrors ai_extraction_jobs). Staff READ their own
--    tenant's rows; all writes come from the backend (service_role bypasses RLS).
--    `drop policy if exists` first so this whole file is safely re-runnable.
alter table public.document_chunks        enable row level security;
alter table public.quiz_generation_jobs   enable row level security;

drop policy if exists "staff reads own tenant document chunks" on public.document_chunks;
create policy "staff reads own tenant document chunks"
  on public.document_chunks
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

drop policy if exists "staff reads own tenant generation jobs" on public.quiz_generation_jobs;
create policy "staff reads own tenant generation jobs"
  on public.quiz_generation_jobs
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

grant select, insert, update, delete on public.document_chunks      to service_role;
grant select, insert, update, delete on public.quiz_generation_jobs to service_role;

-- ============================================================================
-- END OF MIGRATION 32
-- ============================================================================
