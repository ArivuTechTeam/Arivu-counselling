-- Dedicated per-institution gate for the quiz-generator -> ExamApp handoff.
-- Apply after migration 75. This column intentionally does not use the general
-- feature_flags JSON or effective_feature_flags(), whose current platform-wide
-- defaults are unsuitable for a tenant-by-tenant rollout.
begin;

alter table public.tenants
  add column if not exists handwritten_evaluation_enabled boolean not null default false;

commit;
