-- ============================================================================
-- Migration 15 — Quiz extraction: tag extracted questions
-- Run this ONCE in the Supabase SQL Editor.
--
-- The quiz-EXTRACTION feature (Gemini reads a teacher's existing MCQ document
-- and pulls the questions out) needs to distinguish these from AI-*generated*
-- questions and manually-authored ones — for analytics and review filtering.
--
-- This is purely ADDITIVE: it appends one value to an existing enum. No table,
-- column, or existing row is changed. Nothing else in the app is affected.
--
-- Note: the questions table already has `extraction_job_id` and
-- `confidence_score` columns, and the `ai_extraction_jobs` table already
-- exists — the extraction feature reuses those as-is.
-- ============================================================================

alter type question_source add value if not exists 'extracted';

-- ============================================================================
-- END OF MIGRATION 15
-- ============================================================================
