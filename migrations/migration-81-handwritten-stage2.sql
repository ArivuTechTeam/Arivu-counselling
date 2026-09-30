-- Phase C: fixed-rubric direct-score-v2 handwritten evaluation.
begin;

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','processing_stage2','evaluated','review','failed'
 ));
create unique index if not exists uq_handwritten_submissions_id_tenant
 on public.handwritten_submissions(id,tenant_id);

create table if not exists public.handwritten_evaluations(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 submission_id uuid not null unique,
 status text not null default 'completed' check(status='completed'),
 total_marks_obtained numeric not null check(total_marks_obtained>=0),
 total_marks_possible numeric not null check(total_marks_possible>=0),
 percentage numeric not null check(percentage>=0),
 overall_feedback text not null default '',
 strengths jsonb not null default '[]'::jsonb check(jsonb_typeof(strengths)='array'),
 areas_to_improve jsonb not null default '[]'::jsonb check(jsonb_typeof(areas_to_improve)='array'),
 is_ai_evaluated boolean not null default true check(is_ai_evaluated),
 created_at timestamptz not null default now(),
 constraint handwritten_evaluations_submission_scope_fk
  foreign key(submission_id,tenant_id)
  references public.handwritten_submissions(id,tenant_id) on delete cascade,
 unique(id,tenant_id)
);

create table if not exists public.handwritten_question_evaluations(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 question_ref text not null,
 question_text text not null default '',
 marks_obtained numeric not null check(marks_obtained>=0),
 marks_possible numeric not null check(marks_possible>=0),
 not_attempted boolean not null default false,
 not_evaluated boolean not null default false,
 not_counted boolean not null default false,
 mapping_status text not null check(mapping_status in('matched','recovered','unsafe','blank')),
 feedback text not null default '',
 student_guidance jsonb not null default '{}'::jsonb check(jsonb_typeof(student_guidance)='object'),
 student_answer_excerpt text not null default '',
 handwriting_legibility text not null default 'clear',
 grading_confidence numeric not null default 1 check(grading_confidence between 0 and 1),
 criteria_breakdown jsonb not null default '[]'::jsonb check(jsonb_typeof(criteria_breakdown)='array'),
 created_at timestamptz not null default now(),
 constraint handwritten_question_evaluations_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 unique(evaluation_id,question_ref)
);

create table if not exists public.handwritten_stage2_artifacts(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 sequence integer not null check(sequence>0),
 route text not null check(route in('grouped','whole_paper')),
 model text not null default '',
 prompt_revision text not null default '',
 raw_content text not null default '',
 content_bytes integer not null check(content_bytes>=0),
 content_sha256 text not null check(content_sha256~'^[0-9a-f]{64}$'),
 content_omitted boolean not null default false,
 created_at timestamptz not null default now(),
 constraint handwritten_stage2_artifacts_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 unique(evaluation_id,sequence)
);

create index if not exists handwritten_evaluations_tenant_created
 on public.handwritten_evaluations(tenant_id,created_at desc);
create index if not exists handwritten_question_evaluations_tenant_evaluation
 on public.handwritten_question_evaluations(tenant_id,evaluation_id);
create index if not exists handwritten_stage2_artifacts_tenant_evaluation
 on public.handwritten_stage2_artifacts(tenant_id,evaluation_id,sequence);

alter table public.handwritten_evaluations enable row level security;
alter table public.handwritten_question_evaluations enable row level security;
alter table public.handwritten_stage2_artifacts enable row level security;
revoke all on public.handwritten_evaluations,public.handwritten_question_evaluations,
 public.handwritten_stage2_artifacts from public,anon,authenticated;
grant select,insert,update,delete on public.handwritten_evaluations,
 public.handwritten_question_evaluations,public.handwritten_stage2_artifacts to service_role;

create table if not exists public.ai_provider_slots(
 provider text not null,
 holder_id uuid not null,
 expires_at timestamptz not null,
 created_at timestamptz not null default now(),
 primary key(provider,holder_id)
);
alter table public.ai_provider_slots enable row level security;
revoke all on public.ai_provider_slots from public,anon,authenticated;
grant select,insert,update,delete on public.ai_provider_slots to service_role;
create index if not exists ai_provider_slots_expiry on public.ai_provider_slots(provider,expires_at);

create or replace function public.acquire_ai_provider_slot(
 p_provider text,p_holder uuid,p_limit integer,p_ttl_seconds integer
) returns boolean language plpgsql security invoker set search_path='' as $$
declare active_count integer;
begin
 if p_limit<1 or p_ttl_seconds<1 then return false; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('ai-slot:'||p_provider,0));
 delete from public.ai_provider_slots where provider=p_provider and expires_at<=clock_timestamp();
 if exists(select 1 from public.ai_provider_slots where provider=p_provider and holder_id=p_holder) then
  update public.ai_provider_slots set expires_at=clock_timestamp()+make_interval(secs=>p_ttl_seconds)
   where provider=p_provider and holder_id=p_holder;
  return true;
 end if;
 select count(*) into active_count from public.ai_provider_slots where provider=p_provider;
 if active_count>=p_limit then return false; end if;
 insert into public.ai_provider_slots(provider,holder_id,expires_at)
 values(p_provider,p_holder,clock_timestamp()+make_interval(secs=>p_ttl_seconds));
 return true;
end $$;

create or replace function public.release_ai_provider_slot(p_provider text,p_holder uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 delete from public.ai_provider_slots where provider=p_provider and holder_id=p_holder;
 return found;
end $$;

alter table public.ai_rate_limits drop constraint if exists ai_rate_limits_endpoint_check;
alter table public.ai_rate_limits add constraint ai_rate_limits_endpoint_check check(endpoint in(
 'quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
 'question_explain','quiz_extraction','challenge_join','descriptive_grading',
 'paper_generation','handwritten_evaluation'
));
create or replace function public.consume_ai_rate_limit(
 p_tenant_id uuid,p_user_id uuid,p_endpoint text,p_limit integer
) returns table(allowed boolean,retry_after_seconds integer,remaining integer)
language plpgsql security invoker set search_path='' as $$
declare request_time timestamptz:=clock_timestamp(); consumed_count integer; active_window_start timestamptz;
begin
 if p_limit<1 then raise exception 'Rate limit must be a positive integer'; end if;
 if p_endpoint not in('quiz_generation','blueprint_generation','topic_extraction','question_regenerate',
  'question_explain','quiz_extraction','challenge_join','descriptive_grading','paper_generation',
  'handwritten_evaluation') then raise exception 'Unknown rate-limit endpoint'; end if;
 insert into public.ai_rate_limits as limits(tenant_id,user_id,endpoint,window_started_at,request_count,updated_at)
 values(p_tenant_id,p_user_id,p_endpoint,request_time,1,request_time)
 on conflict(tenant_id,user_id,endpoint) do update set
  window_started_at=case when limits.window_started_at<=request_time-interval '1 hour' then request_time else limits.window_started_at end,
  request_count=case when limits.window_started_at<=request_time-interval '1 hour' then 1 else limits.request_count+1 end,
  updated_at=request_time
 where limits.window_started_at<=request_time-interval '1 hour' or limits.request_count<p_limit
 returning limits.request_count,limits.window_started_at into consumed_count,active_window_start;
 if found then return query select true,0,greatest(p_limit-consumed_count,0); return; end if;
 select limits.window_started_at into active_window_start from public.ai_rate_limits limits
  where limits.tenant_id=p_tenant_id and limits.user_id=p_user_id and limits.endpoint=p_endpoint;
 return query select false,greatest(1,ceil(extract(epoch from(active_window_start+interval '1 hour'-request_time)))::integer),0;
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set status='failed',claimed_by=null,
  lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set status='failed',
  error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j where j.submission_id=s.id
  and j.kind='evaluate_submission' and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing','pending_stage1','processing_stage1',
   'stage1_complete','processing_stage2');
 update public.evaluation_papers p set rubric_status='failed',
  rubric_error='Rubric generation could not finish after repeated interruptions.'
 where exists(select 1 from public.evaluation_jobs j where j.evaluation_paper_id=p.id
  and j.tenant_id=p.tenant_id and j.kind='build_rubric'
  and j.status='failed' and j.attempts>=3)
  and p.rubric_status in('not_started','extracting','generating');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3 order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; current_submission public.handwritten_submissions;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  select s.* into current_submission from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled for update of s;
  if not found then return false; end if;
  update public.handwritten_submissions set
   status=case when current_submission.status in('stage1_complete','processing_stage2')
    then 'processing_stage2' else 'processing_stage1' end,
   error_message=null,updated_at=now() where id=current_submission.id;
 elsif selected.kind='build_rubric' then
  if not exists(select 1 from public.evaluation_papers ep
   join public.profiles p on p.id=ep.created_by and p.tenant_id=ep.tenant_id
   join public.tenants t on t.id=ep.tenant_id
   where ep.id=selected.evaluation_paper_id and ep.tenant_id=selected.tenant_id
    and ep.created_by=selected.owner_teacher_id and ep.is_active and p.role='teacher'
    and t.is_active and t.handwritten_evaluation_enabled and ep.rubric_status<>'ready') then return false; end if;
  update public.evaluation_papers set rubric_status='extracting',rubric_error=''
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
    and created_by=selected.owner_teacher_id;
 else return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now() where id=selected.id;
 return true;
end $$;

create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_extraction)<>'object' or nullif(p_source,'') is null then return false; end if;
 update public.handwritten_submissions set stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
 status=case when p_requires_review then 'review' else 'stage1_complete' end,
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 if not found then return false; end if;
 if p_requires_review then
  update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
   where id=selected.id;
 elsif not exists(select 1 from public.handwritten_submissions s
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and p.rubric_status='ready') then
  update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
   where id=selected.id;
 end if;
 return true;
end $$;

create or replace function public.resume_stage2_on_rubric_ready()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if new.rubric_status='ready' and old.rubric_status is distinct from 'ready' then
  update public.evaluation_jobs j set status='queued',claimed_by=null,
   lease_expires_at=null,attempts=0,updated_at=now()
  from public.handwritten_submissions s
  where s.evaluation_paper_id=new.id and s.tenant_id=new.tenant_id
   and s.status='stage1_complete' and j.submission_id=s.id
   and j.tenant_id=s.tenant_id and j.kind='evaluate_submission' and j.status='done'
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 end if;
 return new;
end $$;
drop trigger if exists resume_stage2_on_rubric_ready on public.evaluation_papers;
create trigger resume_stage2_on_rubric_ready after update of rubric_status
 on public.evaluation_papers for each row execute function public.resume_stage2_on_rubric_ready();

create or replace function public.begin_evaluation_stage2(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 update public.handwritten_submissions s set status='processing_stage2',updated_at=now()
  from public.evaluation_papers p where s.id=selected.submission_id
  and s.tenant_id=selected.tenant_id and s.student_id=selected.owner_student_id
  and p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id and p.rubric_status='ready';
 return found;
end $$;

create or replace function public.finish_evaluation_stage2_job(
 p_id uuid,p_worker uuid,p_evaluation uuid,p_summary jsonb,p_questions jsonb,p_artifacts jsonb,p_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; row jsonb;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_summary)<>'object' or jsonb_typeof(p_questions)<>'array'
  or jsonb_typeof(p_artifacts)<>'array' then return false; end if;
 insert into public.handwritten_evaluations(
  id,tenant_id,submission_id,total_marks_obtained,total_marks_possible,percentage,
  overall_feedback,strengths,areas_to_improve
 ) values(
  p_evaluation,selected.tenant_id,selected.submission_id,
  (p_summary->>'total_marks_obtained')::numeric,(p_summary->>'total_marks_possible')::numeric,
  (p_summary->>'percentage')::numeric,coalesce(p_summary->>'overall_feedback',''),
  coalesce(p_summary->'strengths','[]'::jsonb),coalesce(p_summary->'areas_to_improve','[]'::jsonb)
 );
 for row in select value from jsonb_array_elements(p_questions) loop
  insert into public.handwritten_question_evaluations(
   tenant_id,evaluation_id,question_ref,question_text,marks_obtained,marks_possible,
   not_attempted,not_evaluated,not_counted,mapping_status,feedback,student_guidance,
   student_answer_excerpt,handwriting_legibility,grading_confidence,criteria_breakdown
  ) values(selected.tenant_id,p_evaluation,row->>'question_ref',coalesce(row->>'question_text',''),
   (row->>'marks_obtained')::numeric,(row->>'marks_possible')::numeric,
   coalesce((row->>'not_attempted')::boolean,false),coalesce((row->>'not_evaluated')::boolean,false),
   coalesce((row->>'not_counted')::boolean,false),row->>'mapping_status',coalesce(row->>'feedback',''),
   coalesce(row->'student_guidance','{}'::jsonb),coalesce(row->>'student_answer_excerpt',''),
   coalesce(row->>'handwriting_legibility','clear'),coalesce((row->>'grading_confidence')::numeric,1),
   coalesce(row->'criteria_breakdown','[]'::jsonb));
 end loop;
 for row in select value from jsonb_array_elements(p_artifacts) loop
  insert into public.handwritten_stage2_artifacts(
   tenant_id,evaluation_id,sequence,route,model,prompt_revision,raw_content,
   content_bytes,content_sha256,content_omitted
  ) values(selected.tenant_id,p_evaluation,(row->>'sequence')::integer,row->>'route',
   coalesce(row->>'model',''),coalesce(row->>'prompt_revision',''),coalesce(row->>'raw_content',''),
   (row->>'content_bytes')::integer,row->>'content_sha256',coalesce((row->>'content_omitted')::boolean,false));
 end loop;
 update public.handwritten_submissions set status=case when p_review then 'review' else 'evaluated' end,
  error_message=null,updated_at=now() where id=selected.submission_id
  and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 update public.evaluation_jobs set status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_job(p_id uuid,p_worker uuid,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status in('claimed','processing') and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
  into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying and has_stage1 then 'stage1_complete' when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation processing failed.' end,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 return true;
end $$;

update public.evaluation_jobs j set status='queued',claimed_by=null,lease_expires_at=null,updated_at=now()
from public.handwritten_submissions s where j.submission_id=s.id and j.kind='evaluate_submission'
 and j.status='done' and s.status='stage1_complete'
 and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);

revoke all on function public.acquire_ai_provider_slot(text,uuid,integer,integer),
 public.release_ai_provider_slot(text,uuid),public.begin_evaluation_stage2(uuid,uuid),
 public.finish_evaluation_stage2_job(uuid,uuid,uuid,jsonb,jsonb,jsonb,boolean),
 public.resume_stage2_on_rubric_ready()
 from public,anon,authenticated;
grant execute on function public.acquire_ai_provider_slot(text,uuid,integer,integer),
 public.release_ai_provider_slot(text,uuid),public.begin_evaluation_stage2(uuid,uuid),
 public.finish_evaluation_stage2_job(uuid,uuid,uuid,jsonb,jsonb,jsonb,boolean)
 to service_role;

commit;
notify pgrst,'reload schema';
