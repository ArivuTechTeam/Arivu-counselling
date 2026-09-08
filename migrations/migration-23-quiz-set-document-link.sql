-- ============================================================================
-- Migration 23 — Link a quiz set back to the document it came from
-- Apply after migration-22-browser-data-api-hardening.sql.
-- Run this ONCE in the Supabase SQL Editor.
--
-- Adds an OPTIONAL pointer from quiz_sets to the source documents row so the
-- teacher's Document Log can show the status of the quiz produced from each
-- uploaded file (Published / In review / none). Both the AI generation flow
-- and the quiz extraction flow set this when they create a quiz set.
--
-- Additive & safe:
--   * Nullable column + FK + index only — no data rewrite, no dropped column.
--   * Existing quiz_sets rows keep document_id NULL. Only quizzes created AFTER
--     this migration are linked; historical documents show "No quiz yet".
--   * ON DELETE SET NULL: deleting a document never cascades into quiz data.
--
-- IMPORTANT: apply this migration BEFORE deploying the backend that writes
-- document_id, otherwise the insert would fail on a missing column.
-- ============================================================================

alter table public.quiz_sets
  add column if not exists document_id uuid
  references public.documents(id) on delete set null;

create index if not exists idx_quizsets_tenant_document
  on public.quiz_sets (tenant_id, document_id);

-- ============================================================================
-- END OF MIGRATION 23
-- ============================================================================
