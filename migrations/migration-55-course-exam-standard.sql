-- Migration 55 — Course exam scoring standard (Phase 6.2-EX)
-- Apply after migration 54. Binds a policy to a COURSE LEVEL, because one course
-- may have Foundation, Intermediate and Final levels with different rules.
-- The exam simulator scores by that level's real exam standard (e.g. CA Foundation
-- −0.25 vs CMA no negative marking) instead of a single tenant-wide value.
-- Additive + nullable: NULL (every existing course level) = today's exam-config
-- negative marking, and it is only consulted when SCORING_POLICIES_ENABLED is on.
begin;

alter table public.course_levels add column if not exists exam_scoring_policy_id uuid;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'course_levels_exam_policy_tenant_fk'
      and conrelid = 'public.course_levels'::regclass
  ) then
    alter table public.course_levels
      add constraint course_levels_exam_policy_tenant_fk
      foreign key (exam_scoring_policy_id, tenant_id)
      references public.scoring_policies(id, tenant_id) on delete set null (exam_scoring_policy_id);
  end if;
end $$;

commit;
notify pgrst, 'reload schema';
