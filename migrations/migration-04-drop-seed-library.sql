-- ============================================================================
-- Migration 04 — Remove the platform seed library
-- Run this ONCE in the Supabase SQL Editor (top to bottom).
--
-- WHAT THIS DOES: fully reverses Migration 03. Drops the seed_questions table
-- and everything attached to it (its indexes + the super-admin RLS policy) via
-- CASCADE, reclaiming the space. The feature was removed from the app.
--
-- SAFE: uses IF EXISTS, so it is harmless to run even if the table is already
-- gone. Nothing else in the database is touched.
-- ============================================================================

drop table if exists seed_questions cascade;

-- ============================================================================
-- END OF MIGRATION 04
-- ============================================================================
