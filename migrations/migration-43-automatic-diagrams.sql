-- Generated with Supabase CLI. Apply after migrations 41 and 42.
-- Preserve staged immutable visual references in the fenced worker transaction.
begin;
create function public.automatic_diagrams_ready() returns integer
language sql stable security invoker set search_path='' as $$ select 1 $$;
revoke all on function public.automatic_diagrams_ready() from public,anon,authenticated;
grant execute on function public.automatic_diagrams_ready() to service_role;
create or replace function public.finish_faculty_job(p_id uuid,p_token uuid) returns jsonb
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
    if jsonb_typeof(coalesce(item->'media','[]'::jsonb)) <> 'array'
       or jsonb_array_length(coalesce(item->'media','[]'::jsonb)) > 12 then raise exception 'Invalid diagram list'; end if;
    if exists(select 1 from jsonb_array_elements(coalesce(item->'media','[]'::jsonb)) m
      where not exists(select 1 from public.question_assets a where a.id=(m->>'asset_id')::uuid
        and a.tenant_id=j.tenant_id and a.created_by=j.created_by and a.question_id=(item->>'id')::uuid)
      or length(coalesce(m->>'alt','')) not between 1 and 500
      or (m->>'option_id' is not null and not exists(select 1 from jsonb_array_elements(
        coalesce(nullif(item->'options','null'::jsonb),'[]'::jsonb)) o where o->>'id'=m->>'option_id')))
      then raise exception 'Diagram unavailable or invalid for this question'; end if;

    insert into public.questions(id,media,media_version,tenant_id,created_by,chapter_id,topic_id,extraction_job_id,type,question_text,
      options,correct_answer,explanation,difficulty,marks,source,review_status,source_excerpt,
      source_page_start,source_page_end,grounding_confidence,verification_status,verification_warnings,confidence_score)
    values(coalesce((item->>'id')::uuid,gen_random_uuid()),coalesce(item->'media','[]'::jsonb),
      case when jsonb_array_length(coalesce(item->'media','[]'::jsonb))>0 then 1 else 0 end,j.tenant_id,j.created_by,chapter,topic,extraction,(item->>'type')::public.question_type,item->>'question_text',
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
revoke all on function public.finish_faculty_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.finish_faculty_job(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
