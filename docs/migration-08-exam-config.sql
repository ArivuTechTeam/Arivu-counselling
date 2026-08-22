-- ============================================================================
-- Migration 08 — Per-institution exam pattern (Exam Simulator, Phase 3)
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: the Exam Simulator's pattern (how many questions, how long, and
-- the negative-marking penalty) is a per-institution SETTING, not hardcoded — so
-- the same product resells to CA / CMA / JEE / any exam by changing this value.
-- Null means "use the app default"; a config UI can fill it later.
--
-- SAFE + ADDITIVE: one nullable jsonb column on tenants. Nothing else changes.
-- ============================================================================

alter table tenants
  add column if not exists exam_config jsonb;

-- Shape (all optional; app fills gaps with sensible defaults):
--   { "questions": 50, "duration_minutes": 60, "negative_marking": 0.25 }
--
-- Example — set CA Foundation's real pattern for one institution:
--   update tenants
--   set exam_config = '{"questions":100,"duration_minutes":120,"negative_marking":0.25}'
--   where id = '<tenant-id>';

-- ============================================================================
-- END OF MIGRATION 08
-- ============================================================================
