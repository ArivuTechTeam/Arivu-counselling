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
