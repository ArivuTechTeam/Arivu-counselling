-- ============================================================================
-- Migration 15 — Duplicate-upload detection for quiz extraction
-- Run this ONCE in the Supabase SQL Editor.
--
-- Adds a content fingerprint (SHA-256) to documents so we can tell when a
-- teacher re-uploads the EXACT same file. The extraction flow uses this to warn
-- "you already uploaded this file — extract again anyway?" (a soft warning, not
-- a block — multiple quizzes per chapter are still allowed).
--
-- Additive: one nullable column + one index. Existing rows keep content_hash
-- NULL (only files uploaded after this migration get a hash).
-- ============================================================================

alter table documents add column if not exists content_hash text;

create index if not exists idx_documents_tenant_hash
  on documents (tenant_id, content_hash);

-- ============================================================================
-- END OF MIGRATION 15
-- ============================================================================
