-- Atomic review publication and durable whole-quiz regeneration.
-- Apply after migration 74. This migration is additive and does not enqueue work.
begin;

-- Regeneration uses the same leased, tenant-scoped queue as document extraction
-- and blueprint generation. Replace the original inline check constraint.
alter table public.faculty_jobs drop constraint if exists faculty_jobs_kind_check;
alter table public.faculty_jobs add constraint faculty_jobs_kind_check
  check (kind in ('blueprint', 'analysis_quiz', 'extraction', 'regenerate_set'));

create or replace function public.enqueue_faculty_job(
  p_tenant uuid, p_actor uuid, p_key uuid, p_kind text, p_request jsonb,
  p_hash text, p_limit int
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare j public.faculty_jobs; quota record; subject uuid; document uuid; quiz uuid;
begin
  if p_kind not in ('blueprint','analysis_quiz','extraction','regenerate_set') then
    raise exception 'Invalid job kind';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_tenant::text || p_actor::text || p_key::text, 0));
  select * into j from public.faculty_jobs
    where tenant_id=p_tenant and created_by=p_actor and request_key=p_key;
  if found then
    if j.request_hash <> p_hash then return jsonb_build_object('conflict',true); end if;
    return to_jsonb(j);
  end if;
  subject := nullif(p_request->>'subject_id','')::uuid;
  document := nullif(p_request->>'document_id','')::uuid;
  quiz := nullif(p_request->>'quiz_set_id','')::uuid;
  if not exists (select 1 from public.profiles p join public.tenants t on t.id=p.tenant_id
      where p.id=p_actor and p.tenant_id=p_tenant and p.role='teacher' and t.is_active)
    or not exists (select 1 from public.teacher_subjects where tenant_id=p_tenant
      and teacher_id=p_actor and subject_id=subject)
    or not exists (select 1 from public.documents where id=document
      and tenant_id=p_tenant and uploaded_by=p_actor and status::text <> 'archived') then
    raise exception 'Source or subject unavailable';
  end if;
  if p_kind='regenerate_set' and not exists(
    select 1 from public.quiz_sets where id=quiz and tenant_id=p_tenant
      and created_by=p_actor and subject_id=subject and document_id=document
      and status::text='draft' and released_at is null
  ) then raise exception 'Quiz unavailable'; end if;
  select * into quota from public.consume_ai_rate_limit(p_tenant,p_actor,
    case when p_kind='extraction' then 'quiz_extraction'
         when p_kind='regenerate_set' then 'quiz_generation'
         else 'blueprint_generation' end,p_limit);
  if not quota.allowed then
    return jsonb_build_object('rate_limited',true,'retry_after_seconds',quota.retry_after_seconds);
  end if;
  insert into public.faculty_jobs(tenant_id,created_by,request_key,request_hash,kind,request)
    values(p_tenant,p_actor,p_key,p_hash,p_kind,p_request) returning * into j;
  return to_jsonb(j);
end $$;

-- "complete" is for jobs whose service performs its own safe persistence and
-- therefore does not use finish_faculty_job's new-quiz insertion workflow.
create or replace function public.update_faculty_job(
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
  elsif p_action='complete' then
    update public.faculty_jobs set status='completed',phase='completed',result=coalesce(p_payload,'{}'::jsonb),
      checkpoint=null,lease_token=null,lease_expires_at=null,error_message=null,updated_at=now() where id=j.id;
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

-- Find and delete only never-answered rejected questions. Membership and
-- question deletion are one transaction, so a failure cannot detach content.
create or replace function public.purge_rejected_quiz_questions_atomic(
  p_id uuid,p_tenant uuid,p_actor uuid
) returns jsonb language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare chosen uuid[]; purged integer:=0; kept integer:=0;
begin
  perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
  perform 1 from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
  perform 1 from public.questions q where q.id in(
    select l.question_id from public.quiz_variant_questions l
    join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id
  ) order by q.id for update;
  select count(*) into kept
  from public.questions q where q.tenant_id=p_tenant and q.created_by=p_actor
    and q.review_status::text='rejected'
    and q.id in(select l.question_id from public.quiz_variant_questions l
      join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id)
    and (exists(select 1 from public.attempt_answers a where a.question_id=q.id)
      or exists(select 1 from public.practice_answers a where a.question_id=q.id));
  select array_agg(q.id order by q.id) into chosen
  from public.questions q where q.tenant_id=p_tenant and q.created_by=p_actor
    and q.review_status::text='rejected'
    and q.id in(select l.question_id from public.quiz_variant_questions l
      join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id)
    and not exists(select 1 from public.attempt_answers a where a.question_id=q.id)
    and not exists(select 1 from public.practice_answers a where a.question_id=q.id);
  if chosen is null then return jsonb_build_object('purged',0,'kept',coalesce(kept,0)); end if;
  delete from public.quiz_variant_questions l using public.quiz_variants v
    where l.variant_id=v.id and v.quiz_set_id=p_id and l.tenant_id=p_tenant
      and l.question_id=any(chosen);
  delete from public.questions q where q.id=any(chosen) and q.tenant_id=p_tenant
    and q.created_by=p_actor and q.review_status::text='rejected';
  get diagnostics purged = row_count;
  insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
    select p_tenant,p_actor,'teacher','question.purged_rejected','question',id,
      jsonb_build_object('quiz_set_id',p_id) from unnest(chosen) id;
  return jsonb_build_object('purged',purged,'kept',coalesce(kept,0));
end $$;

create or replace function public.publish_quiz_with_rejected_purge_atomic(
  p_id uuid,p_tenant uuid,p_actor uuid,p_token text
) returns jsonb language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; fresh text; purge jsonb; published jsonb;
begin
  perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
  select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
  if s.status::text='published' and s.last_publication_token=p_token then
    return to_jsonb(s)||jsonb_build_object('purged_rejected',0);
  end if;
  if p_token is null or p_token is distinct from (public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token') then
    raise exception 'quiz_changed' using errcode='PT409';
  end if;
  purge:=public.purge_rejected_quiz_questions_atomic(p_id,p_tenant,p_actor);
  fresh:=public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token';
  published:=public.publish_quiz_atomic(p_id,p_tenant,p_actor,fresh);
  update public.quiz_sets set last_publication_token=p_token where id=p_id;
  select to_jsonb(qs) into published from public.quiz_sets qs where qs.id=p_id;
  return published||jsonb_build_object('purged_rejected',coalesce((purge->>'purged')::int,0));
end $$;

create or replace function public.publish_quiz_to_batches_with_rejected_purge_atomic(
 p_id uuid,p_tenant uuid,p_actor uuid,p_token text,p_batch_ids uuid[],p_require_managed boolean
) returns jsonb language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; fresh text; purge jsonb; published jsonb;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 if s.status::text='published' and s.last_publication_token=p_token and s.audience_mode='assigned_batches' then
  return to_jsonb(s)||jsonb_build_object('purged_rejected',0);
 end if;
 if p_token is null or p_token is distinct from (public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token') then
  raise exception 'quiz_changed' using errcode='PT409';
 end if;
 purge:=public.purge_rejected_quiz_questions_atomic(p_id,p_tenant,p_actor);
 fresh:=public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token';
 published:=public.publish_quiz_to_batches_atomic(p_id,p_tenant,p_actor,fresh,p_batch_ids,p_require_managed);
 update public.quiz_sets set last_publication_token=p_token where id=p_id;
 select to_jsonb(qs) into published from public.quiz_sets qs where qs.id=p_id;
 return published||jsonb_build_object('purged_rejected',coalesce((purge->>'purged')::int,0));
end $$;

-- Approve the chosen subset and release it in the same transaction. Unselected
-- questions stay stored for lineage but become immutable with the released quiz;
-- duplicate the quiz to work on them again.
create or replace function public.publish_quiz_blueprint_atomic(
 p_id uuid,p_tenant uuid,p_actor uuid,p_token text,p_selected_ids uuid[],
 p_batch_ids uuid[],p_require_managed boolean
) returns jsonb language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; chosen uuid[]; newly uuid[]; batches uuid[]; v record; n integer; total numeric;
 batch_count integer; selected_count integer; result jsonb;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 perform 1 from public.questions q where q.id in(select l.question_id from public.quiz_variant_questions l
  join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id) order by q.id for update;
 if s.status::text='published' and s.last_publication_token=p_token then
  return to_jsonb(s)||jsonb_build_object('published_count',cardinality(p_selected_ids),'skipped',0);
 end if;
 if s.status::text<>'draft' then raise exception 'quiz_restore_first' using errcode='PT409'; end if;
 if p_token is null or p_token is distinct from (public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token') then
  raise exception 'quiz_changed' using errcode='PT409';
 end if;
 select array_agg(distinct id) into chosen from unnest(p_selected_ids) id;
 if chosen is null or cardinality(chosen)<>cardinality(p_selected_ids) then
  raise exception 'quiz_invalid_selection' using errcode='PT400'; end if;
 select count(distinct q.id) into selected_count from public.questions q
  join public.quiz_variant_questions l on l.question_id=q.id
  join public.quiz_variants v on v.id=l.variant_id
  where v.quiz_set_id=p_id and q.id=any(chosen) and q.tenant_id=p_tenant and q.created_by=p_actor;
 if selected_count<>cardinality(chosen) then raise exception 'quiz_invalid_selection' using errcode='PT400'; end if;
 if exists(select 1 from public.questions q where q.id=any(chosen) and q.review_status::text='rejected')
   or exists(select 1 from public.questions q join public.quiz_variant_questions l on l.question_id=q.id
      join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id
      and q.review_status::text='approved' and not(q.id=any(chosen))) then
  raise exception 'quiz_review_required' using errcode='PT409'; end if;
 select array_agg(q.id) into newly from public.questions q
  where q.id=any(chosen) and q.review_status::text<>'approved';
 update public.questions set review_status='approved',reviewed_by=p_actor,reviewed_at=now()
  where id=any(chosen) and tenant_id=p_tenant and created_by=p_actor and review_status::text<>'approved';
 if newly is not null then
  insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
   select p_tenant,p_actor,'teacher','question.approved','question',id,
    jsonb_build_object('method','blueprint') from unnest(newly) id;
 end if;
 for v in select * from public.quiz_variants where quiz_set_id=p_id order by id loop
  if v.tenant_id<>p_tenant then raise exception 'quiz_no_access' using errcode='PT404'; end if;
  select count(*),sum(coalesce(l.marks_override,q.marks)) into n,total
   from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and q.id=any(chosen);
  if n=0 or total is null or exists(select 1 from public.quiz_variant_questions l
    join public.questions q on q.id=l.question_id where l.variant_id=v.id and q.id=any(chosen)
      and coalesce(l.marks_override,q.marks)<=0) then
   raise exception 'quiz_empty' using errcode='PT409'; end if;
  update public.quiz_variants set total_marks=total where id=v.id;
 end loop;
 if p_batch_ids is not null then
  select array_agg(distinct id) into batches from unnest(p_batch_ids) id;
  if batches is null or cardinality(batches)<>cardinality(p_batch_ids) then
   raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
  select count(*) into batch_count from public.batches b
   join public.subjects subject on subject.id=s.subject_id and subject.tenant_id=p_tenant
   where b.id=any(batches) and b.tenant_id=p_tenant and b.status='active'
    and b.course_id=subject.course_id and b.course_level_id=subject.course_level_id;
  if batch_count<>cardinality(batches) then raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
  if p_require_managed and exists(select 1 from unnest(batches) selected(id) where not exists(
    select 1 from public.batch_memberships member where member.batch_id=selected.id
     and member.tenant_id=p_tenant and member.profile_id=p_actor
     and member.membership_role='teacher' and member.active)) then
   raise exception 'quiz_batch_access' using errcode='PT403'; end if;
 end if;
 update public.questions set release_locked=true where not release_locked and id in(
  select l.question_id from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id
   where v.quiz_set_id=p_id);
 update public.quiz_sets set status='published',published_at=now(),released_at=coalesce(released_at,now()),
  last_publication_token=p_token,audience_mode=case when p_batch_ids is null then audience_mode else 'assigned_batches' end
  where id=p_id;
 select to_jsonb(qs) into result from public.quiz_sets qs where qs.id=p_id;
 if p_batch_ids is not null then
  insert into public.quiz_assignments(tenant_id,quiz_set_id,batch_id,created_by,status)
   select p_tenant,p_id,id,p_actor,'active' from unnest(batches) id
   on conflict (tenant_id,quiz_set_id,batch_id) do update set status='active';
 end if;
 insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
  values(p_tenant,p_actor,'teacher','quiz.published','quiz_set',p_id,
   jsonb_build_object('method','blueprint','question_count',cardinality(chosen)));
 return result||jsonb_build_object('published_count',cardinality(chosen),'skipped',0);
end $$;

revoke all on function public.enqueue_faculty_job(uuid,uuid,uuid,text,jsonb,text,int),
 public.update_faculty_job(uuid,uuid,uuid,uuid,text,jsonb,boolean),
 public.purge_rejected_quiz_questions_atomic(uuid,uuid,uuid),
 public.publish_quiz_with_rejected_purge_atomic(uuid,uuid,uuid,text),
 public.publish_quiz_to_batches_with_rejected_purge_atomic(uuid,uuid,uuid,text,uuid[],boolean),
 public.publish_quiz_blueprint_atomic(uuid,uuid,uuid,text,uuid[],uuid[],boolean)
 from public,anon,authenticated;
grant execute on function public.enqueue_faculty_job(uuid,uuid,uuid,text,jsonb,text,int),
 public.update_faculty_job(uuid,uuid,uuid,uuid,text,jsonb,boolean),
 public.purge_rejected_quiz_questions_atomic(uuid,uuid,uuid),
 public.publish_quiz_with_rejected_purge_atomic(uuid,uuid,uuid,text),
 public.publish_quiz_to_batches_with_rejected_purge_atomic(uuid,uuid,uuid,text,uuid[],boolean),
 public.publish_quiz_blueprint_atomic(uuid,uuid,uuid,text,uuid[],uuid[],boolean)
 to service_role;

commit;
notify pgrst,'reload schema';
