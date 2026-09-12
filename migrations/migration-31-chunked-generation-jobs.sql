-- ============================================================================
-- Migration 31 — Large-document (Map-Reduce) quiz generation
-- Apply after migration-23-quiz-set-document-link.sql.
-- Run this ONCE in the Supabase SQL Editor.
--
-- Adds the state for generating a quiz from a LARGE chapter (> ~40 pages) with a
-- Map-Reduce pipeline:
--   * `document_chunks`         — the document split into overlapping, hashed
--                                 pieces; each also holds its extracted topics
--                                 (the MAP result) and per-chunk status.
--   * `quiz_generation_jobs`    — one row per large-doc analysis run, tracking
--                                 phase/status and holding the consolidated
--                                 Master Blueprint (the REDUCE result).
--
-- Additive & safe:
--   * Two NEW tables + one NEW enum only. No existing table/enum is altered.
--   * The existing (small-document, <=40 pages) generation path is untouched.
--   * Chunks/blueprints are transient generation state — not shown to students,
--     not in analytics. The final quiz is still a normal quiz_set / variant /
--     questions created by existing code.
--   * `job_status` (already defined) is reused for per-chunk MAP status.
--
-- IMPORTANT: apply this migration BEFORE deploying the backend that uses these
-- tables, otherwise the inserts would fail on missing tables.
-- ============================================================================

-- Job-level status for a large-doc analysis run (chunks reuse `job_status`).
-- Guarded so a re-run doesn't error on an already-created type.
do $$ begin
  create type generation_job_status as enum
    ('queued', 'running', 'partial', 'completed', 'failed');
exception when duplicate_object then null;
end $$;

-- One row per chunk of a document: the text, its content hash (for exact
-- de-duplication within the document), and its MAP output + status.
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

-- One row per large-document analysis run: phase/status + the consolidated
-- Master Blueprint produced by the REDUCE step.
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

-- ---------- Row Level Security (mirrors ai_extraction_jobs) ----------
-- Staff READ their own tenant's rows. All writes come from the FastAPI backend
-- using the service_role key (which bypasses RLS), so there is no client-facing
-- write policy — same model as ai_extraction_jobs.
alter table public.document_chunks        enable row level security;
alter table public.quiz_generation_jobs   enable row level security;

create policy "staff reads own tenant document chunks"
  on public.document_chunks
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

create policy "staff reads own tenant generation jobs"
  on public.quiz_generation_jobs
  for select using (
    tenant_id = current_tenant_id() and (is_staff() or is_super_admin())
  );

-- Ensure the backend (service_role) can read/write the new tables.
grant select, insert, update, delete on public.document_chunks      to service_role;
grant select, insert, update, delete on public.quiz_generation_jobs to service_role;

-- ============================================================================
-- END OF MIGRATION 31
-- ============================================================================
