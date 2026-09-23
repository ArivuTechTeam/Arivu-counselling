-- Migration 51 — Course exam scoring standard (Phase 6.2-EX)
-- Apply after migration 50. Binds an official scoring policy to a COURSE, so the
-- exam simulator scores by that course's real exam standard (e.g. CA Foundation
-- −0.25 vs CMA no negative marking) instead of a single tenant-wide value.
-- Additive + nullable: NULL (every existing course) = today's exam-config
-- negative marking, and it is only consulted when SCORING_POLICIES_ENABLED is on.
begin;

alter table public.courses
  add column if not exists exam_scoring_policy_id uuid
    references public.scoring_policies(id) on delete set null;

commit;
notify pgrst, 'reload schema';
