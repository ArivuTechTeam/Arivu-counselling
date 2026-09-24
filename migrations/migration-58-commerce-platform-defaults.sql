-- Migration 58 — make advanced capabilities platform defaults.
--
-- The product is commerce-only, so capability availability is controlled by
-- deployment-wide Railway master switches rather than per-institution opt-in.
-- Existing and future tenants retain an explicit all-enabled snapshot for
-- backwards compatibility with older application versions during rollout.
begin;

update public.tenants
set feature_flags = jsonb_build_object(
  'faculty_jobs', true,
  'quiz_reuse', true,
  'batches', true,
  'scoring_policies', true,
  'commerce_pack', true,
  'figure_attach', true
);

alter table public.tenants
  alter column feature_flags set default '{
    "faculty_jobs": true,
    "quiz_reuse": true,
    "batches": true,
    "scoring_policies": true,
    "commerce_pack": true,
    "figure_attach": true
  }'::jsonb;

-- Per-tenant batch rollout is no longer part of the product model. Tenant,
-- course and level foreign keys continue to enforce isolation and scope.
drop trigger if exists enforce_batch_feature_on_memberships
  on public.batch_memberships;
drop function if exists public.enforce_batch_feature_enabled();

commit;
notify pgrst, 'reload schema';
