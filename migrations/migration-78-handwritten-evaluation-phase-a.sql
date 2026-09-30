-- Phase A: native handwritten-answer evaluation storage, records and queue.
-- Apply after migration 77. No OCR, AI, rubric or grading data is created here.
begin;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values
 ('evaluation-papers','evaluation-papers',false,31457280,
  array['application/pdf','image/png','image/jpeg']),
 ('evaluation-submissions','evaluation-submissions',false,31457280,
  array['application/pdf','image/png','image/jpeg'])
on conflict(id) do update set
 public=false,
 file_size_limit=excluded.file_size_limit,
 allowed_mime_types=excluded.allowed_mime_types;

create unique index if not exists uq_generated_papers_id_tenant
 on public.generated_papers(id,tenant_id);
create unique index if not exists uq_subjects_id_tenant_level
 on public.subjects(id,tenant_id,course_level_id);

create table if not exists public.evaluation_papers(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 course_level_id uuid not null,
 subject_id uuid not null,
 title text not null check(char_length(trim(title)) between 1 and 200),
 question_paper_storage_path text not null unique,
 suggested_answer_storage_path text unique,
 total_marks numeric not null check(total_marks>0),
 generated_paper_id uuid,
 rubric_status text not null default 'not_started' check(rubric_status in('not_started')),
 is_active boolean not null default true,
 created_by uuid not null,
 created_at timestamptz not null default now(),
 constraint evaluation_papers_subject_level_tenant_fk
  foreign key(subject_id,tenant_id,course_level_id)
  references public.subjects(id,tenant_id,course_level_id) on delete cascade,
 constraint evaluation_papers_generated_tenant_fk
  foreign key(generated_paper_id,tenant_id)
  references public.generated_papers(id,tenant_id) on delete set null(generated_paper_id),
 constraint evaluation_papers_creator_tenant_fk
  foreign key(created_by,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 unique(id,tenant_id)
);
create index if not exists evaluation_papers_catalog
 on public.evaluation_papers(tenant_id,course_level_id,subject_id,created_at desc);

create table if not exists public.evaluation_upload_intents(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 evaluation_paper_id uuid not null,
 storage_path text not null unique,
 original_filename text not null check(char_length(original_filename) between 1 and 255),
 content_type text not null check(content_type in('application/pdf','image/png','image/jpeg')),
 expected_size bigint not null check(expected_size between 1 and 31457280),
 status text not null default 'pending' check(status in('pending','verified','consumed','failed')),
 expires_at timestamptz not null default(now()+interval '2 hours'),
 verified_at timestamptz,
 created_at timestamptz not null default now(),
 constraint evaluation_intents_student_tenant_fk
  foreign key(student_id,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 constraint evaluation_intents_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id) on delete cascade,
 unique(id,tenant_id,student_id,evaluation_paper_id)
);
create index if not exists evaluation_intents_owner
 on public.evaluation_upload_intents(tenant_id,student_id,created_at desc);
create index if not exists evaluation_intents_expiry
 on public.evaluation_upload_intents(expires_at) where status='pending';

create table if not exists public.handwritten_submissions(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 evaluation_paper_id uuid not null,
 upload_intent_id uuid not null unique,
 answer_script_path text not null unique,
 additional_pages_path text,
 status text not null default 'pending' check(status in(
  'pending','queued','processing','pending_stage1','evaluated','review','failed'
 )),
 error_message text,
 retrigger_count integer not null default 0 check(retrigger_count>=0),
 regraded_from uuid,
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint handwritten_submissions_intent_scope_fk
  foreign key(upload_intent_id,tenant_id,student_id,evaluation_paper_id)
  references public.evaluation_upload_intents(id,tenant_id,student_id,evaluation_paper_id)
  on delete restrict,
 constraint handwritten_submissions_student_tenant_fk
  foreign key(student_id,tenant_id)
  references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_submissions_paper_tenant_fk
  foreign key(evaluation_paper_id,tenant_id)
  references public.evaluation_papers(id,tenant_id) on delete cascade,
 unique(id,tenant_id,student_id)
);
alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_regraded_scope_fk;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_regraded_scope_fk
 foreign key(regraded_from,tenant_id,student_id)
 references public.handwritten_submissions(id,tenant_id,student_id)
 on delete set null(regraded_from);
create index if not exists handwritten_submissions_owner
 on public.handwritten_submissions(tenant_id,student_id,created_at desc);
create index if not exists handwritten_submissions_paper
 on public.handwritten_submissions(tenant_id,evaluation_paper_id,created_at desc);

create table if not exists public.evaluation_jobs(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 submission_id uuid not null unique,
 kind text not null default 'evaluate_submission' check(kind in('evaluate_submission')),
 status text not null default 'queued' check(status in('queued','claimed','processing','done','failed')),
 owner_student_id uuid not null,
 claimed_by uuid,
 claimed_at timestamptz,
 lease_expires_at timestamptz,
 attempts integer not null default 0 check(attempts between 0 and 3),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint evaluation_jobs_submission_scope_fk
  foreign key(submission_id,tenant_id,owner_student_id)
  references public.handwritten_submissions(id,tenant_id,student_id) on delete cascade
);
create index if not exists evaluation_jobs_queue
 on public.evaluation_jobs(status,created_at)
 where status in('queued','claimed','processing');
create index if not exists evaluation_jobs_owner
 on public.evaluation_jobs(tenant_id,owner_student_id,created_at desc);

alter table public.evaluation_papers enable row level security;
alter table public.evaluation_upload_intents enable row level security;
alter table public.handwritten_submissions enable row level security;
alter table public.evaluation_jobs enable row level security;
revoke all on public.evaluation_papers,public.evaluation_upload_intents,
 public.handwritten_submissions,public.evaluation_jobs from public,anon,authenticated;
grant select,insert,update,delete on public.evaluation_papers,
 public.evaluation_upload_intents,public.handwritten_submissions,public.evaluation_jobs
 to service_role;

drop policy if exists "staff read tenant evaluation papers" on public.evaluation_papers;
create policy "staff read tenant evaluation papers" on public.evaluation_papers
 for select using(tenant_id=current_tenant_id() and is_staff());
drop policy if exists "staff manage tenant evaluation papers" on public.evaluation_papers;
create policy "staff manage tenant evaluation papers" on public.evaluation_papers
 for all using(tenant_id=current_tenant_id() and is_staff())
 with check(tenant_id=current_tenant_id() and is_staff());
drop policy if exists "owners read evaluation intents" on public.evaluation_upload_intents;
create policy "owners read evaluation intents" on public.evaluation_upload_intents
 for select using(tenant_id=current_tenant_id() and (student_id=auth.uid() or is_staff()));
drop policy if exists "owners read handwritten submissions" on public.handwritten_submissions;
create policy "owners read handwritten submissions" on public.handwritten_submissions
 for select using(tenant_id=current_tenant_id() and (student_id=auth.uid() or is_staff()));
drop policy if exists "owners read evaluation jobs" on public.evaluation_jobs;
create policy "owners read evaluation jobs" on public.evaluation_jobs
 for select using(tenant_id=current_tenant_id() and (owner_student_id=auth.uid() or is_staff()));

create or replace function public.create_handwritten_submission_job(
 p_tenant uuid,p_student uuid,p_intent uuid
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare intent public.evaluation_upload_intents;
 submission public.handwritten_submissions;
 job public.evaluation_jobs;
begin
 perform pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended(p_tenant::text||':'||p_student::text||':'||p_intent::text,0)
 );
 select * into intent from public.evaluation_upload_intents
  where id=p_intent and tenant_id=p_tenant and student_id=p_student for update;
 if not found then raise exception 'evaluation_intent_unavailable' using errcode='PT404'; end if;
 select * into submission from public.handwritten_submissions
  where upload_intent_id=p_intent and tenant_id=p_tenant and student_id=p_student;
 if found then
  select * into job from public.evaluation_jobs where submission_id=submission.id;
  return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
 end if;
 if intent.status<>'verified' or intent.expires_at<=now() then
  raise exception 'evaluation_intent_not_verified' using errcode='PT409';
 end if;
 if not exists(
  select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
   where p.id=p_student and p.tenant_id=p_tenant and p.role='student' and t.is_active
 ) or not exists(
  select 1 from public.evaluation_papers ep
  join public.subjects s on s.id=ep.subject_id and s.tenant_id=ep.tenant_id
  join public.enrollments e on e.tenant_id=ep.tenant_id
   and e.profile_id=p_student and e.course_id=s.course_id
   and e.course_level_id=ep.course_level_id
  where ep.id=intent.evaluation_paper_id and ep.tenant_id=p_tenant and ep.is_active
 ) then raise exception 'evaluation_access_denied' using errcode='PT403'; end if;
 insert into public.handwritten_submissions(
  tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,status
 ) values(p_tenant,p_student,intent.evaluation_paper_id,intent.id,intent.storage_path,'queued')
 returning * into submission;
 update public.evaluation_upload_intents set status='consumed'
  where id=intent.id and tenant_id=p_tenant and student_id=p_student;
 insert into public.evaluation_jobs(tenant_id,submission_id,owner_student_id)
 values(p_tenant,submission.id,p_student) returning * into job;
 return jsonb_build_object('submission',to_jsonb(submission),'job',to_jsonb(job));
end $$;

create or replace function public.claim_evaluation_job(p_worker uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 update public.evaluation_jobs j set
  status='failed',claimed_by=null,lease_expires_at=null,updated_at=now()
 where j.status in('claimed','processing') and j.lease_expires_at<now() and j.attempts>=3;
 update public.handwritten_submissions s set
  status='failed',error_message='Processing could not finish after repeated interruptions.',updated_at=now()
 where exists(select 1 from public.evaluation_jobs j
  where j.submission_id=s.id and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing');
 select * into selected from public.evaluation_jobs j
  where (j.status='queued' or (j.status in('claimed','processing') and j.lease_expires_at<now()))
   and j.attempts<3
  order by j.created_at,j.id for update skip locked limit 1;
 if not found then return null; end if;
 update public.evaluation_jobs set
  status='claimed',claimed_by=p_worker,claimed_at=now(),
  lease_expires_at=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
 where id=selected.id returning * into selected;
 return to_jsonb(selected);
end $$;

create or replace function public.start_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status='claimed' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 if not exists(
  select 1 from public.handwritten_submissions s
  join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and s.student_id=selected.owner_student_id and p.role='student'
 ) then return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now() where id=selected.id;
 update public.handwritten_submissions set status='processing',error_message=null,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 return true;
end $$;

create or replace function public.finish_evaluation_stub_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status='processing' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 update public.handwritten_submissions set
  status='pending_stage1',error_message=null,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 if not found then return false; end if;
 update public.evaluation_jobs set
  status='done',claimed_by=null,lease_expires_at=null,updated_at=now()
  where id=selected.id;
 return true;
end $$;

create or replace function public.fail_evaluation_job(
 p_id uuid,p_worker uuid,p_retryable boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs; retrying boolean;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status in('claimed','processing') and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 retrying:=p_retryable and selected.attempts<3;
 update public.evaluation_jobs set
  status=case when retrying then 'queued' else 'failed' end,
  claimed_by=null,lease_expires_at=null,updated_at=now() where id=selected.id;
 update public.handwritten_submissions set
  status=case when retrying then 'queued' else 'failed' end,
  error_message=case when retrying then null else 'Evaluation preparation failed.' end,
  updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 return true;
end $$;

revoke all on function public.create_handwritten_submission_job(uuid,uuid,uuid),
 public.claim_evaluation_job(uuid),public.start_evaluation_job(uuid,uuid),
 public.finish_evaluation_stub_job(uuid,uuid),
 public.fail_evaluation_job(uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function public.create_handwritten_submission_job(uuid,uuid,uuid),
 public.claim_evaluation_job(uuid),public.start_evaluation_job(uuid,uuid),
 public.finish_evaluation_stub_job(uuid,uuid),
 public.fail_evaluation_job(uuid,uuid,boolean) to service_role;

commit;
notify pgrst,'reload schema';
