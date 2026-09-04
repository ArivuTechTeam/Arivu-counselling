-- ============================================================================
-- Migration 09 — Local-dev tenant
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: there is no test/demo tenant concept anywhere in this schema
-- (see migrations/schema.sql's `tenants` table — no is_demo/is_test flag, no
-- reserved naming convention). The only existing tenant row today is the
-- real ArivuPro pilot institution (subdomain = 'arivupro'). This migration
-- adds ONE extra tenant row, clearly separate from it, so local development
-- and testing never writes documents/quiz sets/attempts into ArivuPro's
-- real tenant data.
--
-- SAFE + ADDITIVE: one new row in `tenants`. Nothing else changes. Idempotent
-- via the `subdomain` unique constraint — safe to re-run.
-- ============================================================================

insert into tenants (name, subdomain, plan_tier, is_active)
values ('Local Dev (test tenant — not a real institution)', 'local-dev', 'free', true)
on conflict (subdomain) do nothing;

-- After running, copy this tenant's id into:
--   frontend/.env.local  -> NEXT_PUBLIC_DEFAULT_TENANT_ID
--   root .env (docker-compose) -> NEXT_PUBLIC_DEFAULT_TENANT_ID
select id, name, subdomain from tenants where subdomain = 'local-dev';

-- ============================================================================
-- END OF MIGRATION 09
-- ============================================================================
