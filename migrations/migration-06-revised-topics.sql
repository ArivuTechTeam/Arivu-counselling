-- ============================================================================
-- Migration 06 — Revised topics (student revision list, weak-area side)
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: the student's revision list also surfaces the WEAK TOPICS pulled
-- from their own performance. This table records which of those a student has
-- marked "revised" so they drop off the list. (Bookmarked questions live in the
-- `bookmarks` table from migration 05; this is the topic side.)
--
-- SAFE + ADDITIVE: one new table + index + student-owned RLS.
-- ============================================================================

create table if not exists revised_topics (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id),
  student_id uuid not null references profiles(id) on delete cascade,
  topic_key  text not null,            -- "Subject||Chapter||Topic" (stable across recomputes)
  created_at timestamptz not null default now(),
  unique (student_id, topic_key)
);
create index if not exists idx_revised_topics_student on revised_topics(student_id);

alter table revised_topics enable row level security;
create policy "own revised topics" on revised_topics
  for all
  using      (tenant_id = current_tenant_id()
              and (student_id = auth.uid() or is_staff() or is_super_admin()))
  with check (tenant_id = current_tenant_id() and student_id = auth.uid());

-- ============================================================================
-- END OF MIGRATION 06
-- ============================================================================
