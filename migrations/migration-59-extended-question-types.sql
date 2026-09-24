-- ============================================================================
-- Migration 59 - Extended objective question types (Phase 6.4)
-- Run this ONCE in the Supabase SQL Editor.
--
-- Adds three new auto-graded objective types to the question_type enum:
--   assertion_reason, mrm (multiple-response, partial credit), matching.
--
-- Purely ADDITIVE: it appends values to an existing enum. No table, column, or
-- existing row is changed, and no existing question is affected. These types are
-- only ever PRODUCED when EXTENDED_QUESTION_TYPES_ENABLED is on in the backend;
-- until then the enum simply carries three unused values.
--
-- Note: ALTER TYPE ... ADD VALUE cannot run inside a transaction block, so these
-- statements are intentionally NOT wrapped in begin/commit (matches migration-15).
-- Descriptive/manual grading is intentionally NOT included here - it belongs to
-- the future Mock Test Paper feature.
-- ============================================================================

alter type question_type add value if not exists 'assertion_reason';
alter type question_type add value if not exists 'mrm';
alter type question_type add value if not exists 'matching';

notify pgrst, 'reload schema';

-- ============================================================================
-- END OF MIGRATION 59
-- ============================================================================
