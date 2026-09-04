-- ============================================================================
-- Migration 10 — Enable RLS on plan_limits
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS FIXES: of the 17 tables in this schema, plan_limits was the only
-- one without row level security enabled. Supabase auto-exposes every table
-- via PostgREST, and the anon key is public in the browser bundle, so an
-- unauthenticated client could otherwise read AND write this table directly.
-- plan_limits isn't tenant-scoped (just global pricing-tier rows) and isn't
-- currently queried by any backend or frontend code, but it should still be
-- read-only from the client and closed to writes until a real admin flow
-- needs them.
--
-- SAFE + ADDITIVE: enables RLS and adds one read-only policy. No existing
-- rows or columns change. Idempotent — safe to re-run.
-- ============================================================================

alter table plan_limits enable row level security;

drop policy if exists "anyone can read plan limits" on plan_limits;
create policy "anyone can read plan limits" on plan_limits
  for select using (true);
-- No client-facing write policy — pricing/quota tiers change via a new
-- migration (service_role), never from an anon/authenticated client.

-- ============================================================================
-- END OF MIGRATION 10
-- ============================================================================
