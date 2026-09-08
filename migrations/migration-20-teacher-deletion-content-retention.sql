-- Migration 20 — Preserve academic content when a teacher is removed.
-- Apply after migration-19-quiz-extraction-rate-limit.sql.
--
-- A teacher may own documents, questions, reviews, and quiz sets. Those
-- records must remain available to the institution after the Auth account and
-- cascading profile row are deleted, so their author references become null.

begin;

alter table public.documents
  alter column uploaded_by drop not null,
  drop constraint if exists documents_uploaded_by_fkey,
  add constraint documents_uploaded_by_fkey
    foreign key (uploaded_by) references public.profiles(id) on delete set null;

alter table public.questions
  drop constraint if exists questions_reviewed_by_fkey,
  add constraint questions_reviewed_by_fkey
    foreign key (reviewed_by) references public.profiles(id) on delete set null,
  drop constraint if exists questions_created_by_fkey,
  add constraint questions_created_by_fkey
    foreign key (created_by) references public.profiles(id) on delete set null;

alter table public.quiz_sets
  alter column created_by drop not null,
  drop constraint if exists quiz_sets_created_by_fkey,
  add constraint quiz_sets_created_by_fkey
    foreign key (created_by) references public.profiles(id) on delete set null;

commit;
