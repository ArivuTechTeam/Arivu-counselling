-- Migration 64 - Knowledge base: generalise PYQ into PYQ/MTP/RTP (KB-A)
-- Apply after migration 63. Preserve any Phase-1 PYQ snapshots while moving
-- them to the generalized bank. This migration is additive to the rest of the
-- system and byte-neutral when
-- PAPER_BANK_ENABLED is off. It:
--   1) replaces pyq_questions with a generalised `paper_questions` bank
--      (paper_type in pyq/mtp/rtp, + chapter, + descriptive model_answer/summary),
--   2) generalises the questions PYQ columns into paper_* columns,
--   3) records, per uploaded document, which paper types it contains.
begin;

-- 1) The knowledge-base of classified questions (one table for all three types).
create table if not exists public.paper_questions (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references public.tenants(id) on delete cascade,
  paper_type         text not null check (paper_type in ('pyq', 'mtp', 'rtp')),
  subject_id         uuid not null,              -- student delivery is subject-scoped
  chapter_id         uuid,                        -- optional finer filter
  exam               text,                        -- e.g. "CA Foundation Paper 1"
  year               text,                        -- e.g. "2019", "May 2022"
  type               question_type not null,
  question_text      text not null,
  options            jsonb,
  correct_answer     jsonb,                       -- null for descriptive
  explanation        text,
  marks              numeric not null default 1,
  model_answer       text,                        -- descriptive: suggested answer from the document
  answer_summary     text,                        -- descriptive: AI-condensed key points (for grading)
  content_hash       text not null,
  origin_question_id uuid,                        -- lineage only (snapshot outlives source)
  source_quiz_set_id uuid,
  source_document_id uuid,
  created_by         uuid,
  created_at         timestamptz not null default now(),
  constraint paper_questions_subject_tenant_fk
    foreign key (subject_id, tenant_id)
    references public.subjects(id, tenant_id) on delete cascade
);

-- Dedup within a paper type: same content + year + exam is one entry per tenant.
create unique index if not exists uq_paper_dedup
  on public.paper_questions (tenant_id, paper_type, content_hash, coalesce(year, ''), coalesce(exam, ''));
create index if not exists idx_paper_questions_tenant on public.paper_questions(tenant_id);
-- Serves the student random pull (paper_type + subject + chapter + question type).
create index if not exists idx_paper_questions_bank
  on public.paper_questions(tenant_id, paper_type, subject_id, chapter_id, type);

-- Migration 63 may have been used before this one. Copy existing PYQ rows before
-- removing the old table, retaining their IDs and source lineage. Both steps
-- run inside this transaction, so an insert failure rolls back without data loss.
insert into public.paper_questions (
  id, tenant_id, paper_type, subject_id, exam, year, type, question_text,
  options, correct_answer, explanation, marks, content_hash,
  origin_question_id, source_quiz_set_id, source_document_id, created_by, created_at
)
select
  id, tenant_id, 'pyq', subject_id, pyq_exam, pyq_year, type, question_text,
  options, correct_answer, explanation, marks, content_hash,
  origin_question_id, source_quiz_set_id, source_document_id, created_by, created_at
from public.pyq_questions
on conflict do nothing;

drop table public.pyq_questions;

alter table public.paper_questions enable row level security;
revoke all on public.paper_questions from public, anon, authenticated;
grant select, insert, update, delete on public.paper_questions to service_role;
drop policy if exists "read own tenant papers" on public.paper_questions;
create policy "read own tenant papers" on public.paper_questions
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage papers" on public.paper_questions;
create policy "staff manage papers" on public.paper_questions
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

-- 2) Generalise the questions PYQ columns into paper_* columns.
alter table public.questions
  add column if not exists paper_type text,
  add column if not exists paper_year text,
  add column if not exists paper_exam text,
  add column if not exists paper_source_note text,
  add column if not exists model_answer text,
  add column if not exists answer_summary text;

do $$
begin
  if exists (select 1 from information_schema.columns
             where table_schema = 'public' and table_name = 'questions' and column_name = 'is_pyq') then
    update public.questions
      set paper_type = 'pyq', paper_year = pyq_year, paper_exam = pyq_exam,
          paper_source_note = pyq_source_note
      where coalesce(is_pyq, false) = true;
  end if;
end $$;

alter table public.questions
  drop constraint if exists questions_paper_type_check;
alter table public.questions
  add constraint questions_paper_type_check
    check (paper_type is null or paper_type in ('pyq', 'mtp', 'rtp'));

alter table public.questions
  drop column if exists is_pyq,
  drop column if exists pyq_year,
  drop column if exists pyq_exam,
  drop column if exists pyq_source_note;

-- 3) Knowledge base of documents: which paper types each upload contains.
alter table public.documents
  add column if not exists contains_papers jsonb;   -- e.g. {"pyq":true,"mtp":false,"rtp":false}

commit;
notify pgrst, 'reload schema';
