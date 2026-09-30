-- Phase E: frozen handwritten-evaluation rubric generation.
begin;

alter table public.evaluation_papers
 add column if not exists structured_qa jsonb not null default '{}'::jsonb,
 add column if not exists question_structure jsonb,
 add column if not exists rubric_source text,
 add column if not exists rubric_error text not null default '',
 add column if not exists question_paper_text text,
 add column if not exists suggested_answer_text text;

alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_rubric_status_check;
alter table public.evaluation_papers
 drop constraint if exists evaluation_papers_rubric_source_check,
 drop constraint if exists evaluation_papers_structured_qa_json_check,
 drop constraint if exists evaluation_papers_question_structure_json_check;
alter table public.evaluation_papers
 add constraint evaluation_papers_rubric_status_check check(
  rubric_status in('not_started','extracting','generating','ready','failed')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_rubric_source_check check(
  rubric_source is null or rubric_source in('official','ai_derived')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_structured_qa_json_check check(
  jsonb_typeof(structured_qa) in('object','array')
 );
alter table public.evaluation_papers
 add constraint evaluation_papers_question_structure_json_check check(
  question_structure is null or jsonb_typeof(question_structure)='object'
 );
create unique index if not exists uq_evaluation_papers_creator_scope
 on public.evaluation_papers(id,tenant_id,created_by);

alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_submission_scope_fk;
alter table public.evaluation_jobs
 alter column submission_id drop not null,
 alter column owner_student_id drop not null,
 add column if not exists evaluation_paper_id uuid,
 add column if not exists owner_teacher_id uuid;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_submission_scope_fk
  foreign key(submission_id,tenant_id,owner_student_id)
  references public.handwritten_submissions(id,tenant_id,student_id) on delete cascade;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_paper_scope_fk;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_paper_scope_fk
  foreign key(evaluation_paper_id,tenant_id,owner_teacher_id)
  references public.evaluation_papers(id,tenant_id,created_by) on delete cascade;
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_kind_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_kind_check check(
  kind in('evaluate_submission','build_rubric')
 );
alter table public.evaluation_jobs
 drop constraint if exists evaluation_jobs_target_check;
alter table public.evaluation_jobs
 add constraint evaluation_jobs_target_check check(
  (kind='evaluate_submission' and submission_id is not null
   and owner_student_id is not null and evaluation_paper_id is null
   and owner_teacher_id is null)
  or
  (kind='build_rubric' and submission_id is null
   and owner_student_id is null and evaluation_paper_id is not null
   and owner_teacher_id is not null)
 );
create unique index if not exists uq_evaluation_jobs_rubric_paper
 on public.evaluation_jobs(evaluation_paper_id)
 where kind='build_rubric';
create index if not exists evaluation_jobs_teacher_owner
 on public.evaluation_jobs(tenant_id,owner_teacher_id,created_at desc)
 where owner_teacher_id is not null;

drop policy if exists "owners read evaluation jobs" on public.evaluation_jobs;
create policy "owners read evaluation jobs" on public.evaluation_jobs
 for select using(
  tenant_id=current_tenant_id()
  and (owner_student_id=auth.uid() or owner_teacher_id=auth.uid() or is_staff())
 );

create or replace function public.enqueue_evaluation_rubric_job()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 perform pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(new.tenant_id::text||':rubric:'||new.id::text,0)
 );
 if not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
  where p.id=new.created_by and p.tenant_id=new.tenant_id and p.role='teacher'
   and t.is_active and t.handwritten_evaluation_enabled
 ) then
  raise exception 'rubric_job_teacher_not_authorized' using errcode='PT403';
 end if;
 insert into public.evaluation_jobs(
  tenant_id,evaluation_paper_id,owner_teacher_id,kind
 ) values(new.tenant_id,new.id,new.created_by,'build_rubric')
 on conflict(evaluation_paper_id) where kind='build_rubric' do nothing;
 return new;
end $$;
drop trigger if exists enqueue_evaluation_rubric_job on public.evaluation_papers;
create trigger enqueue_evaluation_rubric_job
 after insert on public.evaluation_papers for each row
 execute function public.enqueue_evaluation_rubric_job();

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
  and s.status in('queued','processing','pending_stage1','processing_stage1');
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
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and status='claimed' and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 if selected.kind='evaluate_submission' then
  if not exists(select 1 from public.handwritten_submissions s
   join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
   join public.tenants t on t.id=s.tenant_id
   where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
    and s.student_id=selected.owner_student_id and p.role='student'
    and t.is_active and t.handwritten_evaluation_enabled) then return false; end if;
  update public.handwritten_submissions set status='processing_stage1',
   error_message=null,updated_at=now() where id=selected.submission_id
   and tenant_id=selected.tenant_id and student_id=selected.owner_student_id;
 elsif selected.kind='build_rubric' then
  if not exists(select 1 from public.evaluation_papers ep
   join public.profiles p on p.id=ep.created_by and p.tenant_id=ep.tenant_id
   join public.tenants t on t.id=ep.tenant_id
   where ep.id=selected.evaluation_paper_id and ep.tenant_id=selected.tenant_id
    and ep.created_by=selected.owner_teacher_id and ep.is_active and p.role='teacher'
    and t.is_active and t.handwritten_evaluation_enabled
    and ep.rubric_status not in('ready')) then return false; end if;
  update public.evaluation_papers set rubric_status='extracting',rubric_error=''
   where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
    and created_by=selected.owner_teacher_id;
 else return false;
 end if;
 update public.evaluation_jobs set status='processing',updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.checkpoint_evaluation_rubric_texts(
 p_id uuid,p_worker uuid,p_question_text text,p_answer_text text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status='processing' and claimed_by=p_worker
  and lease_expires_at>now() for update;
 if not found or nullif(trim(p_question_text),'') is null then return false; end if;
 update public.evaluation_papers set question_paper_text=p_question_text,
  suggested_answer_text=nullif(p_answer_text,''),rubric_status='generating',rubric_error=''
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 return found;
end $$;

create or replace function public.finish_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_structured_qa jsonb,p_structure jsonb,p_source text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status='processing' and claimed_by=p_worker
  and lease_expires_at>now() for update;
 if not found or jsonb_typeof(p_structured_qa)<>'array'
  or (p_structure is not null and jsonb_typeof(p_structure)<>'object')
  or p_source not in('official','ai_derived') then return false; end if;
 update public.evaluation_papers set structured_qa=p_structured_qa,
  question_structure=p_structure,rubric_source=p_source,rubric_status='ready',
  rubric_error='' where id=selected.evaluation_paper_id
  and tenant_id=selected.tenant_id and created_by=selected.owner_teacher_id;
 if not found then return false; end if;
 update public.evaluation_jobs set status='done',claimed_by=null,
  lease_expires_at=null,updated_at=now() where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_rubric_job(
 p_id uuid,p_worker uuid,p_retryable boolean,p_error text
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs where id=p_id
  and kind='build_rubric' and status in('claimed','processing')
  and claimed_by=p_worker and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 update public.evaluation_jobs set status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.evaluation_papers set
  rubric_status=case when retrying then 'not_started' else 'failed' end,
  rubric_error=case when retrying then '' else left(coalesce(p_error,'Rubric generation failed.'),2000) end
  where id=selected.evaluation_paper_id and tenant_id=selected.tenant_id
   and created_by=selected.owner_teacher_id;
 return true;
end $$;

revoke all on function public.enqueue_evaluation_rubric_job(),
 public.checkpoint_evaluation_rubric_texts(uuid,uuid,text,text),
 public.finish_evaluation_rubric_job(uuid,uuid,jsonb,jsonb,text),
 public.fail_evaluation_rubric_job(uuid,uuid,boolean,text)
 from public,anon,authenticated;
grant execute on function public.checkpoint_evaluation_rubric_texts(uuid,uuid,text,text),
 public.finish_evaluation_rubric_job(uuid,uuid,jsonb,jsonb,text),
 public.fail_evaluation_rubric_job(uuid,uuid,boolean,text)
 to service_role;

commit;
notify pgrst,'reload schema';
