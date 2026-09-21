-- Apply after the repository's migrations 01–42. Additive; legacy paths remain available.
-- Only service_role can access this queue/RPCs; HTTP routes enforce teacher ownership.
begin;

create table public.faculty_jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  created_by uuid not null references public.profiles(id) on delete cascade,
  request_key uuid not null,
  request_hash text not null,
  kind text not null check (kind in ('blueprint', 'analysis_quiz', 'extraction')),
  request jsonb not null,
  status text not null default 'queued' check (status in ('queued','running','completed','failed','cancelled')),
  phase text not null default 'queued',
  attempts int not null default 0 check (attempts between 0 and 3),
  lease_token uuid,
  lease_expires_at timestamptz,
  available_at timestamptz not null default now(),
  started_at timestamptz,
  checkpoint jsonb,
  result jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (tenant_id, created_by, request_key)
);
create index faculty_jobs_owner on public.faculty_jobs(tenant_id, created_by, created_at desc);
-- The owner composite index starts with tenant_id, so add the FK column index
-- needed for efficient profiles(id) cascades and owner-only maintenance.
create index faculty_jobs_created_by on public.faculty_jobs(created_by);
create index faculty_jobs_queue on public.faculty_jobs(available_at, created_at) where status in ('queued','running');
create index faculty_jobs_running on public.faculty_jobs(tenant_id, lease_expires_at) where status = 'running';
alter table public.faculty_jobs enable row level security;
revoke all on public.faculty_jobs from public, anon, authenticated;
grant all on public.faculty_jobs to service_role;

create function public.enqueue_faculty_job(
  p_tenant uuid, p_actor uuid, p_key uuid, p_kind text, p_request jsonb,
  p_hash text, p_limit int
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare j public.faculty_jobs; quota record;
begin
  if p_kind not in ('blueprint','analysis_quiz','extraction') then
    raise exception 'Invalid job kind';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_tenant::text || p_actor::text || p_key::text, 0));
  select * into j from public.faculty_jobs
    where tenant_id=p_tenant and created_by=p_actor and request_key=p_key;
  if found then
    if j.request_hash <> p_hash then return jsonb_build_object('conflict',true); end if;
    return to_jsonb(j);
  end if;
  if not exists (select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
      where p.id=p_actor and p.tenant_id=p_tenant and p.role='teacher' and t.is_active)
    or not exists (select 1 from public.teacher_subjects where tenant_id=p_tenant
      and teacher_id=p_actor and subject_id=(p_request->>'subject_id')::uuid)
    or not exists (select 1 from public.documents where id=(p_request->>'document_id')::uuid
      and tenant_id=p_tenant and uploaded_by=p_actor and status::text <> 'archived') then
    raise exception 'Source or subject unavailable';
  end if;
  select * into quota from public.consume_ai_rate_limit(p_tenant,p_actor,
    case when p_kind='extraction' then 'quiz_extraction' else 'blueprint_generation' end,p_limit);
  if not quota.allowed then
    return jsonb_build_object('rate_limited',true,'retry_after_seconds',quota.retry_after_seconds);
  end if;
  insert into public.faculty_jobs(tenant_id,created_by,request_key,request_hash,kind,request)
    values(p_tenant,p_actor,p_key,p_hash,p_kind,p_request) returning * into j;
  return to_jsonb(j);
end $$;

create function public.claim_faculty_job() returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare j public.faculty_jobs;
begin
  -- Serialize the short claim decision so multiple workers respect both caps.
  perform pg_advisory_xact_lock(619202602);
  update public.faculty_jobs set status='failed',phase='failed',lease_token=null,
    lease_expires_at=null,updated_at=now(),error_message='Processing could not finish after repeated interruptions. Start a new request.'
    where status='running' and lease_expires_at < now() and attempts >= 3;
  if (select count(*) from public.faculty_jobs where status='running' and lease_expires_at > now()) >= 4 then
    return null;
  end if;
  select * into j from public.faculty_jobs q
    where ((q.status='queued' and q.available_at <= now())
       or (q.status='running' and q.lease_expires_at < now())) and q.attempts < 3
      and (select count(*) from public.faculty_jobs active where active.tenant_id=q.tenant_id
           and active.status='running' and active.lease_expires_at > now()) < 2
    order by q.available_at,q.created_at,q.id for update skip locked limit 1;
  if not found then return null; end if;
  update public.faculty_jobs set status='running',phase=case when checkpoint is null then 'processing' else 'saving' end,
    attempts=attempts+1,lease_token=gen_random_uuid(),lease_expires_at=now()+interval '120 seconds',
    started_at=now(),updated_at=now(),error_message=null where id=j.id returning * into j;
  return to_jsonb(j);
end $$;

create function public.update_faculty_job(
  p_id uuid,p_tenant uuid,p_actor uuid,p_token uuid,p_action text,
  p_payload jsonb default null,p_retryable boolean default false
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare j public.faculty_jobs;
begin
  select * into j from public.faculty_jobs where id=p_id and tenant_id=p_tenant and created_by=p_actor for update;
  if not found then return false; end if;
  if p_action='cancel' then
    if j.status not in ('queued','running') then return false; end if;
    update public.faculty_jobs set status='cancelled',phase='cancelled',lease_token=null,
      lease_expires_at=null,checkpoint=null,updated_at=now() where id=j.id;
    return true;
  end if;
  if j.status <> 'running' or j.lease_token is distinct from p_token
      or j.lease_expires_at <= now() or j.started_at < now()-interval '60 minutes' then return false; end if;
  if p_action='heartbeat' then
    update public.faculty_jobs set lease_expires_at=now()+interval '120 seconds',updated_at=now() where id=j.id;
  elsif p_action='checkpoint' then
    update public.faculty_jobs set checkpoint=p_payload,phase='saving',updated_at=now() where id=j.id;
  elsif p_action='fail' then
    update public.faculty_jobs set status=case when p_retryable and attempts < 3 then 'queued' else 'failed' end,
      phase=case when p_retryable and attempts < 3 then 'retrying' else 'failed' end,
      available_at=now()+make_interval(secs=>10*j.attempts),lease_token=null,lease_expires_at=null,
      updated_at=now(),error_message=case when p_retryable and attempts < 3
        then 'Processing was interrupted. A retry is queued.'
        else 'We could not finish this request. Check the source and selection before starting again.' end where id=j.id;
  else raise exception 'Invalid job action'; end if;
  return true;
end $$;

create function public.finish_faculty_job(p_id uuid,p_token uuid) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  j public.faculty_jobs; payload jsonb; item jsonb; qid uuid; sid uuid; vid uuid;
  chapter uuid; topic uuid; topic_name text; extraction uuid; position int:=0;
  stored jsonb:='[]'::jsonb; total numeric; result_data jsonb; doc uuid; subject uuid;
begin
  select * into j from public.faculty_jobs where id=p_id for update;
  if not found then raise exception 'Job unavailable'; end if;
  if j.status='completed' then return j.result; end if;
  if j.status <> 'running' or j.lease_token is distinct from p_token or j.lease_expires_at <= now()
     or j.started_at < now()-interval '60 minutes' then raise exception 'Worker lease expired'; end if;
  payload:=j.checkpoint;
  if payload is null or jsonb_array_length(payload->'questions') < 1 then raise exception 'No prepared questions'; end if;
  doc:=(j.request->>'document_id')::uuid; subject:=(j.request->>'subject_id')::uuid;
  if not exists (select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
      where p.id=j.created_by and p.tenant_id=j.tenant_id and p.role='teacher' and t.is_active)
    or not exists (select 1 from public.teacher_subjects where tenant_id=j.tenant_id
      and teacher_id=j.created_by and subject_id=subject)
    or not exists (select 1 from public.documents where id=doc and tenant_id=j.tenant_id
      and uploaded_by=j.created_by and status::text <> 'archived') then raise exception 'Source access changed'; end if;
  -- Serialize same-tenant chapter/topic creation without changing existing schemas.
  perform pg_advisory_xact_lock(hashtextextended(j.tenant_id::text,1));
  if j.kind='extraction' then
    select id into chapter from public.chapters where id=(j.request->>'chapter_id')::uuid
      and tenant_id=j.tenant_id and subject_id=subject;
    if chapter is null then raise exception 'Chapter unavailable'; end if;
    insert into public.ai_extraction_jobs(tenant_id,document_id,status,model_used,raw_output,overall_confidence,completed_at)
      values(j.tenant_id,doc,'succeeded',payload->>'provider',payload,
        (payload->>'overall_confidence')::numeric,now()) returning id into extraction;
  else
    select id into chapter from public.chapters where tenant_id=j.tenant_id and subject_id=subject
      and name=payload->>'chapter_name' order by id limit 1;
    if chapter is null then
      insert into public.chapters(tenant_id,subject_id,name) values(j.tenant_id,subject,payload->>'chapter_name') returning id into chapter;
    end if;
    for topic_name in select jsonb_array_elements_text(payload->'selected_topics') loop
      if not exists(select 1 from public.topics where tenant_id=j.tenant_id and chapter_id=chapter and name=topic_name) then
        insert into public.topics(tenant_id,chapter_id,name) values(j.tenant_id,chapter,topic_name);
      end if;
    end loop;
  end if;
  select sum((q->>'marks')::numeric) into total from jsonb_array_elements(payload->'questions') q;
  if total is null or total <= 0 then raise exception 'Invalid marks'; end if;
  insert into public.quiz_sets(tenant_id,created_by,document_id,subject_id,chapter_id,title,status)
    values(j.tenant_id,j.created_by,doc,subject,chapter,payload->>'title','draft') returning id into sid;
  insert into public.quiz_variants(tenant_id,quiz_set_id,variant_type,total_marks)
    values(j.tenant_id,sid,(payload->>'variant_type')::public.variant_type,total) returning id into vid;
  for item in select * from jsonb_array_elements(payload->'questions') loop
    topic:=null;
    select id into topic from public.topics where tenant_id=j.tenant_id and chapter_id=chapter
      and lower(name)=lower(item->>'topic') order by id limit 1;
    if (item->>'marks')::numeric <= 0 then raise exception 'Invalid question marks'; end if;
    insert into public.questions(tenant_id,created_by,chapter_id,topic_id,extraction_job_id,type,question_text,
      options,correct_answer,explanation,difficulty,marks,source,review_status,source_excerpt,
      source_page_start,source_page_end,grounding_confidence,verification_status,verification_warnings,confidence_score)
    values(j.tenant_id,j.created_by,chapter,topic,extraction,(item->>'type')::public.question_type,item->>'question_text',
      nullif(item->'options','null'::jsonb),item->'correct_answer',item->>'explanation',item->>'difficulty',(item->>'marks')::numeric,
      (payload->>'source')::public.question_source,'pending_review',item->>'source_excerpt',
      (item->>'source_page_start')::int,(item->>'source_page_end')::int,(item->>'grounding_confidence')::numeric,
      coalesce(item->>'verification_status','needs_teacher_review'),coalesce(item->'verification_warnings','[]'::jsonb),
      (item->>'confidence')::numeric) returning id into qid;
    insert into public.quiz_variant_questions(tenant_id,variant_id,question_id,order_index) values(j.tenant_id,vid,qid,position);
    if j.kind <> 'extraction' then
      insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
        values(j.tenant_id,j.created_by,'teacher','question.generated','question',qid,
          jsonb_build_object('type',item->>'type','difficulty',item->>'difficulty',
            'cognitive_level',payload->>'variant_type','subject_id',subject,
            'provider',payload->>'provider','faculty_job_id',j.id));
    end if;
    stored:=stored || jsonb_build_array(item || jsonb_build_object('id',qid)); position:=position+1;
  end loop;
  update public.documents set chapter_id=chapter where id=doc and tenant_id=j.tenant_id and uploaded_by=j.created_by;
  if j.kind='analysis_quiz' then
    update public.quiz_generation_jobs set quiz_set_id=sid,subject_id=subject,chapter_name=payload->>'chapter_name',
      params=params || jsonb_build_object('selected_topics',j.request->'selected_topics')
      where id=(j.request->>'analysis_job_id')::uuid and tenant_id=j.tenant_id and created_by=j.created_by;
    if not found then raise exception 'Original analysis no longer available'; end if;
  end if;
  result_data:=jsonb_build_object('quiz_set_id',sid,'variant_id',vid,'provider',payload->>'provider',
    'blueprint',payload->'blueprint','questions',stored,'extracted',position,
    'skipped',coalesce((payload->'import_summary'->>'skipped')::int,0),
    'import_summary',payload->'import_summary','overall_confidence',payload->'overall_confidence','extraction_job_id',extraction);
  update public.faculty_jobs set status='completed',phase='completed',result=result_data,
    checkpoint=null,lease_token=null,lease_expires_at=null,error_message=null,updated_at=now() where id=j.id;
  return result_data;
end $$;

revoke all on function public.enqueue_faculty_job(uuid,uuid,uuid,text,jsonb,text,int) from public,anon,authenticated;
revoke all on function public.claim_faculty_job() from public,anon,authenticated;
revoke all on function public.update_faculty_job(uuid,uuid,uuid,uuid,text,jsonb,boolean) from public,anon,authenticated;
revoke all on function public.finish_faculty_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.enqueue_faculty_job(uuid,uuid,uuid,text,jsonb,text,int) to service_role;
grant execute on function public.claim_faculty_job() to service_role;
grant execute on function public.update_faculty_job(uuid,uuid,uuid,uuid,text,jsonb,boolean) to service_role;
grant execute on function public.finish_faculty_job(uuid,uuid) to service_role;
notify pgrst, 'reload schema';
commit;
