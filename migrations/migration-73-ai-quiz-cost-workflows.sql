-- Migration 73: metadata-only quiz cost runs and complete filtered rollups.
-- Apply after migration 72; deploy API AND worker after applying.
begin;
create table if not exists public.ai_quiz_workflows (
  id uuid primary key,
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  document_id uuid references public.documents(id) on delete set null,
  quiz_set_id uuid references public.quiz_sets(id) on delete set null,
  kind text not null check (kind in ('generation','extraction')),
  status text not null check (status in ('running','completed','failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
alter table public.ai_quiz_workflows enable row level security;
revoke all on public.ai_quiz_workflows from public,anon,authenticated;
grant select,insert,update,delete on public.ai_quiz_workflows to service_role;
create index if not exists ai_quiz_workflows_document on public.ai_quiz_workflows(document_id);
create index if not exists ai_quiz_workflows_quiz on public.ai_quiz_workflows(quiz_set_id);
create index if not exists ai_quiz_workflows_tenant_time on public.ai_quiz_workflows(tenant_id,started_at desc);
alter table public.api_call_logs add column if not exists workflow_id uuid
  references public.ai_quiz_workflows(id) on delete cascade;
create index if not exists api_call_logs_workflow_time on public.api_call_logs(workflow_id,created_at desc);

create or replace function public.ai_quiz_cost_page(
  p_page integer default 1, p_page_size integer default 20,
  p_tenant uuid default null, p_document uuid default null,
  p_provider text default null, p_status text default null,
  p_from timestamptz default null, p_to timestamptz default null,
  p_kind text default null
) returns jsonb language sql stable security invoker set search_path='' as $$
with filtered as (
 select l.*, w.kind as workflow_kind,w.quiz_set_id,q.title as quiz_title,w.status as workflow_status,
   case when l.workflow_id is not null then 'run:'||l.workflow_id::text
        when l.document_id is not null then 'legacy:'||l.tenant_id::text||':'||l.document_id::text
        else 'unlinked:'||coalesce(l.tenant_id::text,'platform')||':'||l.call_type end as group_key
 from public.api_call_logs l
 left join public.ai_quiz_workflows w on w.id=l.workflow_id and w.tenant_id=l.tenant_id
 left join public.quiz_sets q on q.id=w.quiz_set_id and q.tenant_id=l.tenant_id
 where (p_tenant is null or l.tenant_id=p_tenant)
   and (p_document is null or l.document_id=p_document)
   and (p_provider is null or l.provider=p_provider)
   and (p_status is null or l.status=p_status)
   and (p_from is null or l.created_at>=p_from)
   and (p_to is null or l.created_at<=p_to)
   and (p_kind is null or w.kind=p_kind or (p_kind='legacy' and l.workflow_id is null))
), stages as (
 select group_key,call_type,count(*) as calls,sum(cost_usd) as cost_usd
 from filtered group by group_key,call_type
), grouped as (
 select group_key,
   (array_agg(workflow_id))[1] as workflow_id,
   (array_agg(tenant_id))[1] as tenant_id,
   (array_agg(document_id))[1] as document_id,
   (array_agg(quiz_set_id))[1] as quiz_set_id,
   min(quiz_title) as quiz_title,
   coalesce(min(workflow_kind),case when bool_or(document_id is not null) then 'legacy' else 'unlinked' end) as kind,
   coalesce(min(workflow_status),'historical') as status,
   min(created_at) as started_at,max(created_at) as last_call_at,
   count(*) as call_count,count(*) filter(where status='error') as error_count,
   count(*) filter(where cost_usd is null) as unpriced_calls,
   sum(cost_usd) as cost_usd,sum(cost_inr) as cost_inr,
   coalesce(sum(input_tokens),0) as input_tokens,coalesce(sum(output_tokens),0) as output_tokens,
   coalesce(sum(thinking_tokens),0) as thinking_tokens,coalesce(sum(cached_tokens),0) as cached_tokens,
   sum(latency_ms) as provider_latency_ms
 from filtered group by group_key
), page_rows as (
 select g.*, (select jsonb_agg(jsonb_build_object('call_type',s.call_type,'calls',s.calls,'cost_usd',s.cost_usd)
    order by s.call_type) from stages s where s.group_key=g.group_key) as stages
 from grouped g order by last_call_at desc,group_key
 limit least(greatest(p_page_size,1),50)
 offset (greatest(p_page,1)-1)*least(greatest(p_page_size,1),50)
)
select jsonb_build_object(
 'items',coalesce((select jsonb_agg(to_jsonb(r) order by r.last_call_at desc,r.group_key) from page_rows r),'[]'::jsonb),
 'total',(select count(*) from grouped),
 'cost_usd',(select sum(cost_usd) from filtered),
 'call_count',(select count(*) from filtered),
 'unpriced_calls',(select count(*) from filtered where cost_usd is null)
);
$$;
revoke all on function public.ai_quiz_cost_page(integer,integer,uuid,uuid,text,text,timestamptz,timestamptz,text) from public,anon,authenticated;
grant execute on function public.ai_quiz_cost_page(integer,integer,uuid,uuid,text,text,timestamptz,timestamptz,text) to service_role;
commit;
