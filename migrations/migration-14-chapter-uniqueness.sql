-- ============================================================================
-- Migration 14 — Chapter integrity: no duplicate chapters within a subject
-- Run this ONCE in the Supabase SQL Editor.
--
-- Chapters are deduped today only in application code (the POST /chapters
-- get-or-create). This adds a DATABASE-level guarantee so a (tenant, subject,
-- name) chapter can never be duplicated — even from a future code path or a
-- race. Stronger SaaS integrity; supports the quiz-extraction chapter mapping.
--
-- Additive: creates a unique index. It does NOT change any column or row.
--
-- ⚠️ BEFORE running, check there are no existing duplicates (should return 0 rows):
--     select tenant_id, subject_id, name, count(*)
--     from chapters
--     group by tenant_id, subject_id, name
--     having count(*) > 1;
--   If any rows come back, merge/rename those chapters first, then run this.
-- ============================================================================

create unique index if not exists uq_chapters_tenant_subject_name
  on chapters (tenant_id, subject_id, name);

-- ============================================================================
-- END OF MIGRATION 14
-- ============================================================================
