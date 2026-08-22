-- ============================================================================
-- Migration 07 — Challenge a Friend (student dashboard, Phase 2)
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: a challenge is a FROZEN set of questions a student creates and
-- shares (same institution only). Anyone who takes it does so as a normal
-- practice_session tagged with challenge_id — so the leaderboard is just those
-- graded sessions. No redundant scores are stored on the challenge itself.
--
-- SAFE + ADDITIVE: one new table + one nullable column on practice_sessions.
-- ============================================================================

create table if not exists challenges (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  creator_id   uuid not null references profiles(id),
  creator_name text,                                  -- denormalised for display
  question_ids jsonb not null default '[]'::jsonb,    -- FROZEN — every taker gets these
  share_token  text not null unique,                  -- the shareable link id
  created_at   timestamptz not null default now()
);
create index if not exists idx_challenges_tenant on challenges(tenant_id);
create index if not exists idx_challenges_token  on challenges(share_token);

-- Link a practice_session to the challenge it belongs to (creator or friend).
alter table practice_sessions
  add column if not exists challenge_id uuid references challenges(id);
create index if not exists idx_practice_sessions_challenge
  on practice_sessions(challenge_id);

-- ── RLS: same-institution can VIEW a challenge; only the creator makes one ───
alter table challenges enable row level security;
create policy "same-institution can read challenges" on challenges
  for select using (tenant_id = current_tenant_id());
create policy "create own challenges" on challenges
  for insert with check (tenant_id = current_tenant_id() and creator_id = auth.uid());
create policy "staff manage challenges" on challenges
  for all
  using      (tenant_id = current_tenant_id() and (is_staff() or is_super_admin()))
  with check (tenant_id = current_tenant_id() and (is_staff() or is_super_admin()));

-- ============================================================================
-- END OF MIGRATION 07
-- ============================================================================
