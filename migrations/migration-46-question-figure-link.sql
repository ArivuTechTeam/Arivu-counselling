-- Migration 46 — link a generated question to a source-document figure (Phase 2).
--
-- Additive + nullable. A question MAY carry one figure extracted from its source
-- document (see migration-45). Deleting the figure only clears the link via
-- ON DELETE SET NULL — it never deletes the question. Attachment is gated in app
-- code by FIGURE_ATTACH_ENABLED, is best-effort (never blocks generation), and is
-- confirmed/adjusted by the teacher in the review queue.
begin;

alter table public.questions
  add column if not exists figure_id uuid
    references public.document_figures(id) on delete set null;

-- Partial index: only linked questions are worth indexing (most carry no figure).
create index if not exists idx_questions_figure_id
  on public.questions(figure_id) where figure_id is not null;

commit;

notify pgrst, 'reload schema';
