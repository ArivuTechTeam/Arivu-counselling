-- ============================================================================
-- Migration 02 — Events ledger (append-only instrumentation)
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: a single append-only table that records WHAT HAPPENED and WHEN.
-- Every meaningful action (a question generated, edited, approved, a quiz
-- submitted, a document uploaded) writes ONE row here. Our product-intelligence
-- dashboards read summaries FROM this table (computed by the database), instead
-- of scanning the whole app's tables every time.
--
-- It is SAFE and ADDITIVE: it creates one new table + indexes + read policies.
-- It changes nothing that already exists. The app keeps working with or without
-- it (event logging is best-effort and never blocks a user action).
-- ============================================================================


-- ── The ledger ──────────────────────────────────────────────────────────────
create table if not exists events (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  actor_id     uuid,             -- who did it (null = system); no FK so a
                                 -- deleted user never erases their history
  actor_role   text,            -- denormalised (super_admin/teacher/student…)
                                 -- so we can slice fast without a join
  event_type   text not null,   -- e.g. 'question.approved', 'attempt.submitted'
  subject_type text,            -- 'question' | 'quiz_set' | 'attempt' | 'document'
  subject_id   uuid,            -- the thing it's about
  metadata     jsonb not null default '{}'::jsonb,  -- flexible extra detail
  created_at   timestamptz not null default now()
);


-- ── Indexes (so summaries stay fast at any size) ────────────────────────────
-- "by tenant, newest first"  — powers per-institution, time-ranged reads
create index if not exists idx_events_tenant_time on events(tenant_id, created_at desc);
-- "by event type, newest first" — powers 'all approvals in the last 30 days'
create index if not exists idx_events_type_time   on events(event_type, created_at desc);
-- "everything about this entity" — powers 'was this question edited?'
create index if not exists idx_events_subject      on events(subject_type, subject_id);


-- ── Row Level Security (same isolation model as the rest of the schema) ─────
alter table events enable row level security;

-- Reads: a super admin sees everything; other staff see only their institution.
-- (Students don't read the ledger.)
create policy "events readable by staff in tenant or super admin" on events
  for select using (
    is_super_admin()
    or (tenant_id = current_tenant_id() and is_staff())
  );

-- NOTE ON WRITES (intentional): there is NO insert/update/delete policy.
-- That makes the table append-only and unwritable from the browser. Our backend
-- writes events using the Supabase SERVICE ROLE key, which bypasses RLS — the
-- same way every other server-side write in this project already works.

-- ============================================================================
-- END OF MIGRATION 02
-- ============================================================================
