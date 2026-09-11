-- Revision topics are performance snapshots, not permanent dismissals.
-- When the answered count later increases and the topic is still weak, the
-- application shows it again. Existing rows default to zero; legacy name-based
-- keys naturally stop matching the new stable id-based keys.

alter table public.revised_topics
  add column if not exists answered_at_revision integer not null default 0;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'revised_topics_answered_at_revision_nonnegative'
      and conrelid = 'public.revised_topics'::regclass
  ) then
    alter table public.revised_topics
      add constraint revised_topics_answered_at_revision_nonnegative
      check (answered_at_revision >= 0);
  end if;
end $$;
