-- ============================================================================
-- Migration 18 — Catalog integrity: no duplicate courses / subjects
-- Run this ONCE in the Supabase SQL Editor.
--
-- Mirrors the chapter uniqueness (migration-16) one level up, so a teacher/admin
-- can't accidentally create the same course twice, or the same subject twice
-- within a course. The API also does get-or-create (reuse), and these indexes
-- are the database-level backstop.
--
--   * courses:  unique per institution by name
--   * subjects: unique per (institution, course) by name
--
-- Additive: two unique indexes only.
--
-- ⚠️ BEFORE running, confirm there are no existing duplicates (both should
--    return 0 rows). If any come back, merge/rename them first.
--     select tenant_id, name, count(*) from courses
--       group by tenant_id, name having count(*) > 1;
--     select tenant_id, course_id, name, count(*) from subjects
--       group by tenant_id, course_id, name having count(*) > 1;
-- ============================================================================

create unique index if not exists uq_courses_tenant_name
  on courses (tenant_id, name);

create unique index if not exists uq_subjects_tenant_course_name
  on subjects (tenant_id, course_id, name);

-- ============================================================================
-- END OF MIGRATION 18
-- ============================================================================
