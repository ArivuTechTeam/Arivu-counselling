-- Migration 57 — tenant-scoped rollout controls for advanced capabilities.
-- Railway flags remain master switches; these persisted flags decide which
-- institution may use each enabled capability.
begin;

alter table public.tenants
  add column if not exists feature_flags jsonb not null default '{}'::jsonb;

alter table public.tenants
  drop constraint if exists tenants_feature_flags_object_check;
alter table public.tenants
  add constraint tenants_feature_flags_object_check
  check (jsonb_typeof(feature_flags) = 'object');

create or replace function public.enforce_batch_feature_enabled()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if not exists (
    select 1
    from public.tenants t
    where t.id = new.tenant_id
      and coalesce((t.feature_flags->>'batches')::boolean, false)
  ) then
    raise exception 'Batch management is not enabled for this institution';
  end if;
  return new;
end;
$$;

drop trigger if exists enforce_batch_feature_on_memberships
  on public.batch_memberships;
create trigger enforce_batch_feature_on_memberships
  before insert or update on public.batch_memberships
  for each row execute function public.enforce_batch_feature_enabled();

revoke all on function public.enforce_batch_feature_enabled()
  from public, anon, authenticated, service_role;

commit;
notify pgrst, 'reload schema';
