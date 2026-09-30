-- Phase B: Stage 1 handwritten OCR/transcription and lease-safe persistence.
begin;

alter table public.handwritten_submissions
 add column if not exists stage1_extraction jsonb not null default '{}'::jsonb,
 add column if not exists stage1_extraction_source text,
 add column if not exists page_mapping jsonb;

alter table public.handwritten_submissions
 drop constraint if exists handwritten_submissions_status_check;
alter table public.handwritten_submissions
 add constraint handwritten_submissions_status_check check(status in(
  'pending','queued','processing','pending_stage1','processing_stage1',
  'stage1_complete','evaluated','review','failed'
 ));

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
  and j.status='failed' and j.attempts>=3)
  and s.status in('queued','processing','pending_stage1','processing_stage1');
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
 select * into selected from public.evaluation_jobs
  where id=p_id and status='claimed' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 if not exists(
  select 1 from public.handwritten_submissions s
  join public.profiles p on p.id=s.student_id and p.tenant_id=s.tenant_id
  join public.tenants t on t.id=s.tenant_id
  where s.id=selected.submission_id and s.tenant_id=selected.tenant_id
   and s.student_id=selected.owner_student_id and p.role='student'
   and t.is_active and t.handwritten_evaluation_enabled
 ) then return false; end if;
 update public.evaluation_jobs set status='processing',updated_at=now()
  where id=selected.id;
 update public.handwritten_submissions set
  status='processing_stage1',error_message=null,updated_at=now()
  where id=selected.submission_id and tenant_id=selected.tenant_id
   and student_id=selected.owner_student_id;
 return true;
end $$;

create or replace function public.heartbeat_evaluation_job(p_id uuid,p_worker uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 update public.evaluation_jobs set
  lease_expires_at=now()+interval '120 seconds',updated_at=now()
 where id=p_id and status in('claimed','processing') and claimed_by=p_worker
  and lease_expires_at>now();
 return found;
end $$;

create or replace function public.finish_evaluation_stage1_job(
 p_id uuid,p_worker uuid,p_extraction jsonb,p_source text,p_mapping jsonb,
 p_requires_review boolean
) returns boolean language plpgsql security invoker set search_path='' as $$
declare selected public.evaluation_jobs;
begin
 select * into selected from public.evaluation_jobs
  where id=p_id and status='processing' and claimed_by=p_worker
   and lease_expires_at>now() for update;
 if not found then return false; end if;
 if jsonb_typeof(p_extraction)<>'object' or p_source is null or p_source='' then
  return false;
 end if;
 update public.handwritten_submissions set
  stage1_extraction=p_extraction,
  stage1_extraction_source=p_source,
  page_mapping=coalesce(page_mapping,nullif(p_mapping,'{}'::jsonb)),
  status=case when p_requires_review then 'review' else 'stage1_complete' end,
  error_message=null,updated_at=now()
 where id=selected.submission_id and tenant_id=selected.tenant_id
  and student_id=selected.owner_student_id;
 if not found then return false; end if;
 update public.evaluation_jobs set status='done',claimed_by=null,
  lease_expires_at=null,updated_at=now() where id=selected.id;
 return true;
end $$;

revoke all on function public.heartbeat_evaluation_job(uuid,uuid),
 public.finish_evaluation_stage1_job(uuid,uuid,jsonb,text,jsonb,boolean)
 from public,anon,authenticated;
grant execute on function public.heartbeat_evaluation_job(uuid,uuid),
 public.finish_evaluation_stage1_job(uuid,uuid,jsonb,text,jsonb,boolean)
 to service_role;

commit;
notify pgrst,'reload schema';
