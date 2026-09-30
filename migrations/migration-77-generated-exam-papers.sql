-- Add tenant-configured exam-paper formats and durable generated-paper jobs.
-- Apply after migration 76. Additive; no existing paper/profile data is rewritten.
begin;

alter table public.paper_profiles
  add column if not exists format_config jsonb not null default '{}'::jsonb;
alter table public.paper_profiles drop constraint if exists paper_profiles_format_config_object;
alter table public.paper_profiles add constraint paper_profiles_format_config_object
  check (jsonb_typeof(format_config) = 'object');

-- Required by the composite tenant-safe foreign key below.  The level primary
-- key is globally unique, but PostgreSQL still requires an exact unique key for
-- a composite foreign-key target.
create unique index if not exists uq_course_levels_id_tenant
  on public.course_levels(id, tenant_id);

create table if not exists public.generated_papers (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  course_level_id uuid not null,
  subject_id uuid not null,
  mode text not null check (mode in ('exact_mark','candidate_ai')),
  requested_total_marks numeric not null check (
    requested_total_marks > 0 and requested_total_marks * 2 = trunc(requested_total_marks * 2)
  ),
  selected_question_ids uuid[] not null default '{}'::uuid[],
  status text not null default 'pending' check (status in ('pending','processing','ready','failed')),
  instructions_text text,
  paper_payload jsonb check (paper_payload is null or jsonb_typeof(paper_payload) = 'object'),
  error_message text,
  created_by uuid not null,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint generated_papers_level_tenant_fk
    foreign key (course_level_id, tenant_id)
    references public.course_levels(id, tenant_id) on delete cascade,
  constraint generated_papers_subject_tenant_fk
    foreign key (subject_id, tenant_id)
    references public.subjects(id, tenant_id) on delete cascade,
  constraint generated_papers_creator_tenant_fk
    foreign key (created_by, tenant_id)
    references public.profiles(id, tenant_id) on delete cascade
);
create index if not exists generated_papers_history
  on public.generated_papers(tenant_id, course_level_id, created_at desc);
create index if not exists generated_papers_owner
  on public.generated_papers(tenant_id, created_by, created_at desc);

alter table public.generated_papers enable row level security;
revoke all on public.generated_papers from public, anon, authenticated;
grant select, insert, update, delete on public.generated_papers to service_role;
drop policy if exists "read own tenant generated papers" on public.generated_papers;
create policy "read own tenant generated papers" on public.generated_papers
  for select using (tenant_id = current_tenant_id() or is_super_admin());
drop policy if exists "staff manage generated papers" on public.generated_papers;
create policy "staff manage generated papers" on public.generated_papers
  for all using (tenant_id = current_tenant_id() and is_staff())
  with check (tenant_id = current_tenant_id() and is_staff());

alter table public.faculty_jobs drop constraint if exists faculty_jobs_kind_check;
alter table public.faculty_jobs add constraint faculty_jobs_kind_check
  check (kind in ('blueprint','analysis_quiz','extraction','regenerate_set','generate_paper'));

alter table public.ai_rate_limits drop constraint if exists ai_rate_limits_endpoint_check;
alter table public.ai_rate_limits add constraint ai_rate_limits_endpoint_check check (endpoint in (
  'quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
  'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation'
));

create or replace function public.consume_ai_rate_limit(
  p_tenant_id uuid, p_user_id uuid, p_endpoint text, p_limit integer
)
returns table (allowed boolean, retry_after_seconds integer, remaining integer)
language plpgsql security invoker set search_path = '' as $$
declare
  request_time timestamptz := clock_timestamp();
  consumed_count integer;
  active_window_start timestamptz;
begin
  if p_limit < 1 then raise exception 'Rate limit must be a positive integer'; end if;
  if p_endpoint not in (
    'quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
    'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation'
  ) then raise exception 'Unknown rate-limit endpoint'; end if;
  insert into public.ai_rate_limits as limits(
    tenant_id,user_id,endpoint,window_started_at,request_count,updated_at
  ) values (p_tenant_id,p_user_id,p_endpoint,request_time,1,request_time)
  on conflict (tenant_id,user_id,endpoint) do update set
    window_started_at=case when limits.window_started_at <= request_time-interval '1 hour'
      then request_time else limits.window_started_at end,
    request_count=case when limits.window_started_at <= request_time-interval '1 hour'
      then 1 else limits.request_count+1 end,
    updated_at=request_time
  where limits.window_started_at <= request_time-interval '1 hour'
     or limits.request_count < p_limit
  returning limits.request_count,limits.window_started_at
  into consumed_count,active_window_start;
  if found then
    return query select true,0,greatest(p_limit-consumed_count,0); return;
  end if;
  select limits.window_started_at into active_window_start from public.ai_rate_limits limits
   where limits.tenant_id=p_tenant_id and limits.user_id=p_user_id and limits.endpoint=p_endpoint;
  return query select false,greatest(1,ceil(extract(epoch from(
    active_window_start+interval '1 hour'-request_time)))::integer),0;
end $$;

create or replace function public.enqueue_generated_paper_job(
  p_id uuid, p_tenant uuid, p_actor uuid, p_key uuid, p_request jsonb,
  p_hash text, p_limit integer
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  existing public.faculty_jobs;
  created public.faculty_jobs;
  quota record;
  requested_subject_id uuid := nullif(p_request->>'subject_id','')::uuid;
  requested_level_id uuid := nullif(p_request->>'course_level_id','')::uuid;
  requested numeric := nullif(p_request->>'requested_total_marks','')::numeric;
  selected_mode text := p_request->>'mode';
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_tenant::text||p_actor::text||p_key::text,0)
  );
  select * into existing from public.faculty_jobs
   where tenant_id=p_tenant and created_by=p_actor and request_key=p_key;
  if found then
    if existing.request_hash<>p_hash or existing.kind<>'generate_paper' then
      return jsonb_build_object('conflict',true);
    end if;
    return to_jsonb(existing);
  end if;
  if selected_mode not in ('exact_mark','candidate_ai') or requested<=0
     or requested*2<>trunc(requested*2) then raise exception 'Invalid paper request'; end if;
  if not exists(
    select 1 from public.profiles profile join public.tenants tenant on tenant.id=profile.tenant_id
     where profile.id=p_actor and profile.tenant_id=p_tenant and profile.role='teacher' and tenant.is_active
  ) or not exists(
    select 1 from public.teacher_subjects assignment
     where assignment.tenant_id=p_tenant and assignment.teacher_id=p_actor
       and assignment.subject_id=requested_subject_id
  ) or not exists(
    select 1 from public.subjects s
     where s.id=requested_subject_id and s.tenant_id=p_tenant
       and s.course_level_id=requested_level_id
  ) or not exists(
    select 1 from public.paper_profiles profile
     where profile.tenant_id=p_tenant and profile.course_level_id=requested_level_id
  ) then raise exception 'Paper scope unavailable'; end if;
  select * into quota from public.consume_ai_rate_limit(
    p_tenant,p_actor,'paper_generation',p_limit
  );
  if not quota.allowed then return jsonb_build_object(
    'rate_limited',true,'retry_after_seconds',quota.retry_after_seconds
  ); end if;
  insert into public.generated_papers(
    id,tenant_id,course_level_id,subject_id,mode,requested_total_marks,created_by
  ) values (
    p_id,p_tenant,requested_level_id,requested_subject_id,selected_mode,requested,p_actor
  );
  p_request := p_request||jsonb_build_object('generated_paper_id',p_id);
  insert into public.faculty_jobs(
    tenant_id,created_by,request_key,request_hash,kind,request
  ) values (p_tenant,p_actor,p_key,p_hash,'generate_paper',p_request)
  returning * into created;
  return to_jsonb(created);
end $$;

revoke all on function public.consume_ai_rate_limit(uuid,uuid,text,integer),
  public.enqueue_generated_paper_job(uuid,uuid,uuid,uuid,jsonb,text,integer)
  from public,anon,authenticated;
grant execute on function public.consume_ai_rate_limit(uuid,uuid,text,integer),
  public.enqueue_generated_paper_job(uuid,uuid,uuid,uuid,jsonb,text,integer)
  to service_role;

commit;
notify pgrst, 'reload schema';
