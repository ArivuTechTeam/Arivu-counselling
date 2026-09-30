-- Handwritten evaluation hardening: bounded retries, recovery, history safety,
-- re-evaluation plumbing, and descriptive-section marks.
begin;

alter table public.evaluation_papers
 add column if not exists mcq_marks numeric;
alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_mcq_marks_check;
alter table public.evaluation_papers
 add constraint evaluation_papers_mcq_marks_check check(
  mcq_marks is null or (mcq_marks>=0 and mcq_marks<=total_marks)
 );

alter table public.handwritten_submissions
 add column if not exists paper_title_snapshot text,
 add column if not exists subject_name_snapshot text;
update public.handwritten_submissions s set
 paper_title_snapshot=coalesce(s.paper_title_snapshot,p.title,'Deleted evaluation paper'),
 subject_name_snapshot=coalesce(s.subject_name_snapshot,sub.name,'Deleted subject')
from public.evaluation_papers p
left join public.subjects sub on sub.id=p.subject_id and sub.tenant_id=p.tenant_id
where s.evaluation_paper_id=p.id and s.tenant_id=p.tenant_id
 and (s.paper_title_snapshot is null or s.subject_name_snapshot is null);
update public.handwritten_submissions set
 paper_title_snapshot=coalesce(paper_title_snapshot,'Deleted evaluation paper'),
 subject_name_snapshot=coalesce(subject_name_snapshot,'Deleted subject');
alter table public.handwritten_submissions
 alter column paper_title_snapshot set not null,
 alter column subject_name_snapshot set not null,
 alter column upload_intent_id drop not null,
 alter column evaluation_paper_id drop not null;
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_answer_script_path_key;
create index if not exists handwritten_submissions_answer_script_path
 on public.handwritten_submissions(answer_script_path);

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','processing_stage2','evaluated','review','failed',
  'blocked_rubric_failed'
 ));

create unique index if not exists uq_evaluation_intents_owner_scope
 on public.evaluation_upload_intents(id,tenant_id,student_id);
alter table public.evaluation_upload_intents
 add column if not exists purpose text not null default 'primary',
 add column if not exists submission_id uuid,
 alter column evaluation_paper_id drop not null;
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_upload_intents_purpose_check;
alter table public.evaluation_upload_intents
 add constraint evaluation_upload_intents_purpose_check check(
  purpose in('primary','additional_pages')
 );
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_paper_tenant_fk;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id)
  on delete set null(evaluation_paper_id);
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_submission_scope_fk;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_submission_scope_fk
  foreign key(submission_id,tenant_id,student_id)
  references public.handwritten_submissions(id,tenant_id,student_id)
  on delete cascade;
alter table public.evaluation_upload_intents
 drop constraint if exists evaluation_intents_target_check;
alter table public.evaluation_upload_intents
 add constraint evaluation_intents_target_check check(
  (purpose='primary' and submission_id is null)
  or (purpose='additional_pages' and submission_id is not null)
 );

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_intent_scope_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_intent_scope_fk
  foreign key(upload_intent_id,tenant_id,student_id)
  references public.evaluation_upload_intents(id,tenant_id,student_id)
  on delete restrict;
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_paper_tenant_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id)
  on delete set null(evaluation_paper_id);

alter table public.evaluation_jobs
 add column if not exists available_at timestamptz not null default now(),
 add column if not exists processing_started_at timestamptz,
 add column if not exists last_failure_reason text;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_attempts_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_attempts_check check(attempts between 0 and 4);
drop index if exists public.evaluation_jobs_queue;
create index evaluation_jobs_queue
 on public.evaluation_jobs(status,available_at,created_at)
 where status in('queued','claimed','processing');

create or replace function public.evaluation_retry_delay(p_attempts integer)
returns interval language sql immutable security invoker set search_path='' as $$
 select case
  when p_attempts<=1 then interval '30 seconds'
  when p_attempts=2 then interval '60 seconds'
  else interval '120 seconds'
 end
$$;

create or replace function public.create_limited_handwritten_submission_job(
 p_tenant uuid,p_student uuid,p_intent uuid,p_limit integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents;
 submission public.handwritten_submissions;
 job public.evaluation_jobs;
 paper public.evaluation_papers;
 subject_name text;
 completed integer;
 active integer;
begin
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 if p_limit<1 then raise exception 'evaluation_attempt_limit_invalid'; end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
  p_tenant::text||':'||p_student::text||':'||intent.evaluation_paper_id::text,0
 ));
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 if intent.purpose<>'primary' then
  raise exception 'evaluation_intent_wrong_purpose' using errcode='PT409';
 end if;
 select * into submission from public.handwritten_submissions
  where upload_intent_id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if found then
  select * into job from public.evaluation_jobs where submission_id=submission.id;
  return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
 end if;
 if intent.status<>'verified' or intent.expires_at<=now() then
  raise exception 'evaluation_intent_not_verified' using errcode='PT409';
 end if;
 select count(*) into completed from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=intent.evaluation_paper_id;
 select count(distinct s.id) into active from public.handwritten_submissions s
  join public.evaluation_jobs j on j.submission_id=s.id and j.tenant_id=s.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=intent.evaluation_paper_id
   and j.status in('queued','claimed','processing')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 if completed>=p_limit or completed+active>=p_limit then
  raise exception 'evaluation_attempt_limit_reached' using errcode='PT409';
 end if;
 select ep.* into paper from public.evaluation_papers ep
  join public.subjects s on s.id=ep.subject_id and s.tenant_id=ep.tenant_id
  join public.enrollments e on e.tenant_id=ep.tenant_id
   and e.profile_id=p_student and e.course_id=s.course_id
   and e.course_level_id=ep.course_level_id
  where ep.id=intent.evaluation_paper_id and ep.tenant_id=p_tenant and ep.is_active;
 if not found or not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
   where p.id=p_student and p.tenant_id=p_tenant and p.role='student' and t.is_active
 ) then raise exception 'evaluation_access_denied' using errcode='PT403'; end if;
 select s.name into subject_name from public.subjects s
  where s.id=paper.subject_id and s.tenant_id=paper.tenant_id;
 insert into public.handwritten_submissions(
  tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,
  paper_title_snapshot,subject_name_snapshot,status
 ) values(
  p_tenant,p_student,paper.id,intent.id,intent.storage_path,
  paper.title,coalesce(subject_name,'Deleted subject'),'queued'
 ) returning * into submission;
 update public.evaluation_upload_intents set status='consumed'
  where id=intent.id and tenant_id=p_tenant and student_id=p_student;
 insert into public.evaluation_jobs(
  tenant_id,submission_id,owner_student_id,available_at
 ) values(p_tenant,submission.id,p_student,now()) returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 perform public.reap_stuck_evaluation_jobs(780);
 select * into selected from public.evaluation_jobs j
  where j.status='queued' and j.available_at<=clock_timestamp() and j.attempts<4
  order by j.available_at,j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set status='claimed',claimed_by=p_worker,
  claimed_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '120 seconds',
  attempts=attempts+1,processing_started_at=null,last_failure_reason=null,updated_at=clock_timestamp()
  where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; current_submission public.handwritten_submissions;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  select s.* into current_submission from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled for update of s;
  if not found or current_submission.evaluation_paper_id is null then return false; end if;
  update public.handwritten_submissions set
   status=case when current_submission.status in('stage1_complete','processing_stage2')
    then 'processing_stage2' else 'processing_stage1' end,
   error_message=null,updated_at=clock_timestamp() where id=current_submission.id;
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
 update public.evaluation_jobs set status='processing',processing_started_at=clock_timestamp(),
  updated_at=clock_timestamp() where id=selected.id;
 return true;
end $$;

create or replace function public.timeout_evaluation_job(
 p_id uuid,p_worker uuid,p_reason text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; delay interval; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status in('claimed','processing') and claimed_by=p_worker for update;
 if not found then return jsonb_build_object('changed',false); end if;
 retrying:=selected.attempts<4;
 delay:=public.evaluation_retry_delay(selected.attempts);
 update public.evaluation_jobs set
  status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+delay else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason=left(coalesce(nullif(trim(p_reason),''),'Evaluation processing timed out.'),2000),
  updated_at=clock_timestamp() where id=selected.id;
 if selected.kind='evaluate_submission' then
  select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
   into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
  update public.handwritten_submissions set
   status=case when retrying and has_stage1 then 'stage1_complete'
    when retrying then 'queued' else 'failed' end,
   error_message=case when retrying then null else left(coalesce(p_reason,'Evaluation processing timed out.'),2000) end,
   updated_at=clock_timestamp() where id=selected.submission_id and tenant_id=selected.tenant_id;
 else
  update public.evaluation_papers set
   rubric_status=case when retrying then 'not_started' else 'failed' end,
   rubric_error=case when retrying then '' else left(coalesce(p_reason,'Rubric generation timed out.'),2000) end
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id;
 end if;
 return jsonb_build_object('changed',true,'retrying',retrying,
  'available_at',case when retrying then clock_timestamp()+delay else null end);
end $$;

create or replace function public.reap_stuck_evaluation_jobs(p_soft_timeout_seconds integer default 780)
returns integer language plpgsql security invoker set search_path='' as $$
declare stale record; reaped integer:=0; worker uuid;
begin
 if p_soft_timeout_seconds<1 then raise exception 'soft timeout must be positive'; end if;
 for stale in
  select id,claimed_by from public.evaluation_jobs
  where status in('claimed','processing') and claimed_by is not null and (
   lease_expires_at<=clock_timestamp()
   or coalesce(processing_started_at,claimed_at,updated_at)
      <=clock_timestamp()-make_interval(secs=>p_soft_timeout_seconds)
  ) order by updated_at for update skip locked
 loop
  worker:=stale.claimed_by;
  perform public.timeout_evaluation_job(stale.id,worker,'Evaluation processing exceeded its safe duration.');
  reaped:=reaped+1;
 end loop;
 return reaped;
end $$;

create or replace function public.fail_evaluation_job(p_id uuid,p_worker uuid,p_retryable boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean; has_stage1 boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status in('claimed','processing') and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<4;
 select coalesce(jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb,false)
  into has_stage1 from public.handwritten_submissions where id=selected.submission_id;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+public.evaluation_retry_delay(selected.attempts) else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason='Evaluation processing failed.',updated_at=clock_timestamp() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying and has_stage1 then 'stage1_complete' when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation processing failed.' end,updated_at=clock_timestamp()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 return true;
end $$;

create or replace function public.fail_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_retryable boolean,p_error text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status in('claimed','processing')
  and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<4;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  available_at=case when retrying then clock_timestamp()+public.evaluation_retry_delay(selected.attempts) else available_at end,
  claimed_by=null,claimed_at=null,lease_expires_at=null,processing_started_at=null,
  last_failure_reason=left(coalesce(p_error,'Rubric generation failed.'),2000),updated_at=clock_timestamp()
  where id=selected.id;
 update public.evaluation_papers set
  rubric_status=case when retrying then 'not_started' else 'failed' end,
  rubric_error=case when retrying then '' else left(coalesce(p_error,'Rubric generation failed.'),2000) end
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 if not retrying then
  update public.handwritten_submissions set status='blocked_rubric_failed',
   error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
   updated_at=clock_timestamp()
   where evaluation_paper_id=selected.evaluation_paper_id
    and tenant_id=selected.tenant_id and status='stage1_complete'
    and not exists(select 1 from public.handwritten_evaluations e
     where e.submission_id=handwritten_submissions.id);
 end if;
 return true;
end $$;

create or replace function public.block_submission_for_failed_rubric(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select j.* into selected from public.evaluation_jobs j
  join public.handwritten_submissions s on s.id=j.submission_id and s.tenant_id=j.tenant_id
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where j.id=p_id and j.kind='evaluate_submission' and j.status='processing'
   and j.claimed_by=p_worker and j.lease_expires_at>clock_timestamp()
   and p.rubric_status='failed' for update of j,s;
 if not found then return false; end if;
 update public.handwritten_submissions set status='blocked_rubric_failed',
  error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
  updated_at=clock_timestamp() where id=selected.submission_id and tenant_id=selected.tenant_id;
 update public.evaluation_jobs set status='done',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,updated_at=clock_timestamp() where id=selected.id;
 return true;
end $$;

create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; rubric text;
begin
 select * into selected from public.evaluation_jobs where id=p_id and kind='evaluate_submission'
  and status='processing' and claimed_by=p_worker and lease_expires_at>clock_timestamp() for update;
 if not found or jsonb_typeof(p_extraction)<>'object' or nullif(p_source,'') is null then return false; end if;
 select p.rubric_status into rubric from public.handwritten_submissions s
  join public.evaluation_papers p on p.id=s.evaluation_paper_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id;
 update public.handwritten_submissions set stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
  status=case when p_requires_review then 'review'
   when rubric='failed' then 'blocked_rubric_failed' else 'stage1_complete' end,
  error_message=case when rubric='failed' then
   'Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.'
   else null end,updated_at=clock_timestamp()
  where id=selected.submission_id and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 if not found then return false; end if;
 if p_requires_review or rubric is distinct from 'ready' then
  update public.evaluation_jobs set status='done',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,updated_at=clock_timestamp() where id=selected.id;
 end if;
 return true;
end $$;

create or replace function public.resume_stage2_on_rubric_ready()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if new.rubric_status='ready' and old.rubric_status is distinct from 'ready' then
  update public.evaluation_jobs j set status='queued',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
   last_failure_reason=null,updated_at=clock_timestamp()
  from public.handwritten_submissions s
  where s.evaluation_paper_id=new.id and s.tenant_id=new.tenant_id
   and s.status in('stage1_complete','blocked_rubric_failed')
   and j.submission_id=s.id and j.tenant_id=s.tenant_id
   and j.kind='evaluate_submission' and j.status in('done','failed')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
  update public.handwritten_submissions set status='stage1_complete',error_message=null,
   updated_at=clock_timestamp() where evaluation_paper_id=new.id and tenant_id=new.tenant_id
   and status='blocked_rubric_failed'
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=handwritten_submissions.id);
 end if;
 return new;
end $$;

create or replace function public.reset_evaluation_rubric(p_tenant uuid,p_paper uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 update public.evaluation_papers set structured_qa='{}'::jsonb,question_structure=null,
  rubric_source=null,rubric_error='',question_paper_text=null,suggested_answer_text=null,
  rubric_status='not_started' where id=p_paper and tenant_id=p_tenant;
 if not found then return false; end if;
 update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
  last_failure_reason=null,updated_at=clock_timestamp()
  where evaluation_paper_id=p_paper and tenant_id=p_tenant and kind='build_rubric';
 return found;
end $$;

create or replace function public.attach_handwritten_additional_pages(
 p_tenant uuid,p_student uuid,p_submission uuid,p_intent uuid
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents; submission public.handwritten_submissions; job public.evaluation_jobs;
begin
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_submission::text,0));
 select * into submission from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if exists(select 1 from public.handwritten_evaluations where submission_id=submission.id) then
  raise exception 'completed_submission_is_immutable' using errcode='PT409';
 end if;
 select * into intent from public.evaluation_upload_intents where id=p_intent
  and tenant_id=p_tenant and student_id=p_student and submission_id=p_submission
  and purpose='additional_pages' for update;
 if not found or intent.status<>'verified' or intent.expires_at<=clock_timestamp() then
  raise exception 'additional_pages_intent_not_verified' using errcode='PT409';
 end if;
 update public.handwritten_submissions set additional_pages_path=intent.storage_path,
  stage1_extraction='{}'::jsonb,stage1_extraction_source=null,page_mapping=null,
  status='queued',error_message=null,retrigger_count=retrigger_count+1,
  updated_at=clock_timestamp() where id=submission.id returning * into submission;
 update public.evaluation_upload_intents set status='consumed' where id=intent.id;
 update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
  last_failure_reason=null,updated_at=clock_timestamp()
  where submission_id=submission.id returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.retrigger_handwritten_submission(
 p_tenant uuid,p_student uuid,p_submission uuid,p_limit integer
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare original public.handwritten_submissions; next_submission public.handwritten_submissions;
 job public.evaluation_jobs; completed integer; active integer;
begin
 if p_limit<1 then raise exception 'evaluation_attempt_limit_invalid'; end if;
 select * into original from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if original.evaluation_paper_id is null then
  raise exception 'evaluation_paper_deleted' using errcode='PT409';
 end if;
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
  p_tenant::text||':'||p_student::text||':'||original.evaluation_paper_id::text,0
 ));
 select * into original from public.handwritten_submissions where id=p_submission
  and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'submission_not_found' using errcode='PT404'; end if;
 if original.evaluation_paper_id is null then
  raise exception 'evaluation_paper_deleted' using errcode='PT409';
 end if;
 select count(*) into completed from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=original.evaluation_paper_id;
 if completed>=p_limit then raise exception 'evaluation_attempt_limit_reached' using errcode='PT409'; end if;
 if exists(select 1 from public.evaluation_jobs j where j.submission_id=original.id
  and j.status in('queued','claimed','processing')) then
  raise exception 'evaluation_already_active' using errcode='PT409';
 end if;
 select count(distinct s.id) into active from public.handwritten_submissions s
  join public.evaluation_jobs j on j.submission_id=s.id and j.tenant_id=s.tenant_id
  where s.tenant_id=p_tenant and s.student_id=p_student
   and s.evaluation_paper_id=original.evaluation_paper_id and s.id<>original.id
   and j.status in('queued','claimed','processing')
   and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);
 if completed+active>=p_limit then
  raise exception 'evaluation_attempt_limit_reached' using errcode='PT409';
 end if;
 if exists(select 1 from public.handwritten_evaluations where submission_id=original.id) then
  if exists(select 1 from public.handwritten_submissions s join public.evaluation_jobs j on j.submission_id=s.id
   where s.regraded_from=original.id and s.tenant_id=p_tenant and s.student_id=p_student
    and j.status in('queued','claimed','processing')) then
   raise exception 'evaluation_already_active' using errcode='PT409';
  end if;
  insert into public.handwritten_submissions(
   tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,
   additional_pages_path,status,retrigger_count,regraded_from,paper_title_snapshot,
   subject_name_snapshot,stage1_extraction,stage1_extraction_source,page_mapping
  ) values(
   original.tenant_id,original.student_id,original.evaluation_paper_id,null,
   original.answer_script_path,original.additional_pages_path,'queued',original.retrigger_count+1,
   original.id,original.paper_title_snapshot,original.subject_name_snapshot,
   original.stage1_extraction,original.stage1_extraction_source,original.page_mapping
  ) returning * into next_submission;
  insert into public.evaluation_jobs(tenant_id,submission_id,owner_student_id,available_at)
   values(p_tenant,next_submission.id,p_student,clock_timestamp()) returning * into job;
 else
  if original.status not in('failed','blocked_rubric_failed','stage1_complete','review') then
   raise exception 'submission_cannot_be_retriggered' using errcode='PT409';
  end if;
  update public.handwritten_submissions set status=case
   when jsonb_typeof(stage1_extraction)='object' and stage1_extraction<>'{}'::jsonb then 'stage1_complete'
   else 'queued' end,error_message=null,retrigger_count=retrigger_count+1,updated_at=clock_timestamp()
   where id=original.id returning * into next_submission;
  update public.evaluation_jobs set status='queued',claimed_by=null,claimed_at=null,
   lease_expires_at=null,processing_started_at=null,attempts=0,available_at=clock_timestamp(),
   last_failure_reason=null,updated_at=clock_timestamp()
   where submission_id=original.id returning * into job;
 end if;
 return jsonb_build_object('submission',to_jsonb(next_submission),'job',to_jsonb(job),
  'completed_attempts',completed,'attempt_limit',p_limit);
end $$;

create or replace function public.mark_handwritten_submission_failed(
 p_tenant uuid,p_submission uuid,p_reason text
) returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if nullif(trim(p_reason),'') is null then raise exception 'failure_reason_required'; end if;
 update public.handwritten_submissions set status='failed',error_message=left(trim(p_reason),2000),
  updated_at=clock_timestamp() where id=p_submission and tenant_id=p_tenant
  and status not in('evaluated','review');
 if not found then return false; end if;
 update public.evaluation_jobs set status='failed',claimed_by=null,claimed_at=null,
  lease_expires_at=null,processing_started_at=null,last_failure_reason=left(trim(p_reason),2000),
  updated_at=clock_timestamp() where submission_id=p_submission and tenant_id=p_tenant;
 return true;
end $$;

update public.handwritten_submissions s set status='blocked_rubric_failed',
 error_message='Evaluation is blocked because this paper rubric failed. The submission will resume after the rubric is regenerated.',
 updated_at=clock_timestamp()
from public.evaluation_papers p
where s.evaluation_paper_id=p.id and s.tenant_id=p.tenant_id
 and s.status='stage1_complete' and p.rubric_status='failed'
 and not exists(select 1 from public.handwritten_evaluations e where e.submission_id=s.id);

revoke all on function public.evaluation_retry_delay(integer),
 public.create_limited_handwritten_submission_job(uuid,uuid,uuid,integer),
 public.timeout_evaluation_job(uuid,uuid,text),public.reap_stuck_evaluation_jobs(integer),
 public.block_submission_for_failed_rubric(uuid,uuid),public.reset_evaluation_rubric(uuid,uuid),
 public.attach_handwritten_additional_pages(uuid,uuid,uuid,uuid),
 public.retrigger_handwritten_submission(uuid,uuid,uuid,integer),
 public.mark_handwritten_submission_failed(uuid,uuid,text)
 from public,anon,authenticated;
grant execute on function public.evaluation_retry_delay(integer),
 public.create_limited_handwritten_submission_job(uuid,uuid,uuid,integer),
 public.timeout_evaluation_job(uuid,uuid,text),public.reap_stuck_evaluation_jobs(integer),
 public.block_submission_for_failed_rubric(uuid,uuid),public.reset_evaluation_rubric(uuid,uuid),
 public.attach_handwritten_additional_pages(uuid,uuid,uuid,uuid),
 public.retrigger_handwritten_submission(uuid,uuid,uuid,integer),
 public.mark_handwritten_submission_failed(uuid,uuid,text)
 to service_role;

commit;
notify pgrst,'reload schema';
