-- Migration 63 - PYQ (Previous Year Questions), Phase 1 / PYQ-A
-- Apply after migration 62. Additive + nullable + flag-gated (PAPER_BANK_ENABLED,
-- default off): with the flag off, every existing row and flow is unchanged and
-- these columns/table simply sit unused. It adds:
--   1) PYQ metadata columns on `questions` (replacing the v1 explanation-prefix
--      hack) so draft -> review -> publish can be PYQ-aware and teacher-editable.
--   2) `pyq_questions`: the student-facing PYQ library. At publish time each
--      approved is_pyq question is snapshotted here (frozen copy), de-duplicated
--      by (tenant, content_hash, year, exam), scoped to a subject for delivery.
-- Backend writes via the service-role key; RLS mirrors paper_profiles/scoring.
begin;

-- 1) PYQ metadata on questions (additive, non-breaking).
alter table public.questions add column if not exists is_pyq boolean not null default false;
alter table public.questions add column if not exists pyq_year text;
alter table public.questions add column if not exists pyq_exam text;
alter table public.questions add column if not exists pyq_source_note text;

-- 2) The PYQ library. Content is a frozen snapshot taken at publish, independent
-- of the source question's later life (edits/archive), so a PYQ is permanent.
create table if not exists public.pyq_questions (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references public.tenants(id) on delete cascade,
  subject_id         uuid not null,               -- student delivery is subject-scoped
  pyq_year           text,                         -- e.g. "2019", "May 2022"
  pyq_exam           text,                         -- e.g. "CA Foundation Paper 1"
  type               question_type not null,
  question_text      text not null,
  options            jsonb,
  correct_answer     jsonb not null,
  explanation        text,
  marks              numeric not null default 1,
  content_hash       text not null,                -- fingerprint of the question content
  origin_question_id uuid,                         -- lineage only (no FK: snapshot outlives source)
  source_quiz_set_id uuid,
  source_document_id uuid,
  created_by         uuid,
  created_at         timestamptz not null default now(),
  constraint pyq_questions_subject_tenant_fk
    foreign key (subject_id, tenant_id)
    references public.subjects(id, tenant_id) on delete cascade
);

-- Dedup: the same question content + year + exam is one PYQ per tenant, no matter
-- how many uploads contain it. NULL year/exam collapse to '' so they compare.
create unique index if not exists uq_pyq_dedup
  on public.pyq_questions (tenant_id, content_hash, coalesce(pyq_year, ''), coalesce(pyq_exam, ''));
create index if not exists idx_pyq_questions_tenant on public.pyq_questions(tenant_id);
create index if not exists idx_pyq_questions_subject on public.pyq_questions(subject_id);
-- Serves the student "papers grouped by exam + year within a subject" query.
create index if not exists idx_pyq_questions_paper on public.pyq_questions(subject_id, pyq_exam, pyq_year);

alter table public.pyq_questions enable row level security;
revoke all on public.pyq_questions from public, anon, authenticated;
grant select, insert, update, delete on public.pyq_questions to service_role;

-- Any member of the tenant may read its PYQ (the API applies the enrolled-subject
-- filter); staff manage. Backend uses the service role, so this is defence in depth.
drop policy if exists "read own tenant pyq" on public.pyq_questions;
create policy "read own tenant pyq" on public.pyq_questions
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage pyq" on public.pyq_questions;
create policy "staff manage pyq" on public.pyq_questions
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

commit;
notify pgrst, 'reload schema';
