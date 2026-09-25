-- Publish and restrict to selected batches in one transaction. Apply after migration 66.
begin;

create or replace function public.publish_quiz_to_batches_atomic(
 p_id uuid, p_tenant uuid, p_actor uuid, p_token text, p_batch_ids uuid[], p_require_managed boolean
) returns jsonb
language plpgsql security invoker set search_path=public as $$
declare s public.quiz_sets; chosen uuid[]; batch_count integer;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 if s.status='published' and s.last_publication_token=p_token
    and s.audience_mode='assigned_batches' then return to_jsonb(s); end if;
 if s.status='published' then raise exception 'quiz_changed' using errcode='PT409'; end if;
 select array_agg(distinct batch_id) into chosen from unnest(p_batch_ids) batch_id;
 if chosen is null or cardinality(chosen)<>cardinality(p_batch_ids) then
  raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
 select count(*) into batch_count from public.batches b
  join public.subjects subject on subject.id=s.subject_id and subject.tenant_id=p_tenant
  where b.id=any(chosen) and b.tenant_id=p_tenant and b.status='active'
   and b.course_id=subject.course_id and b.course_level_id=subject.course_level_id;
 if batch_count<>cardinality(chosen) then
  raise exception 'quiz_invalid_batches' using errcode='PT400'; end if;
 if p_require_managed and exists(
  select 1 from unnest(chosen) selected(id) where not exists(
   select 1 from public.batch_memberships member
   where member.batch_id=selected.id and member.tenant_id=p_tenant
    and member.profile_id=p_actor and member.membership_role='teacher' and member.active
  )
 ) then raise exception 'quiz_batch_access' using errcode='PT403'; end if;
 perform public.publish_quiz_atomic(p_id,p_tenant,p_actor,p_token);
 insert into public.quiz_assignments(tenant_id,quiz_set_id,batch_id,created_by,status)
 select p_tenant,p_id,batch_id,p_actor,'active' from unnest(chosen) batch_id
 on conflict (tenant_id,quiz_set_id,batch_id) do update set status='active';
 update public.quiz_sets set audience_mode='assigned_batches'
  where id=p_id and tenant_id=p_tenant returning * into s;
 return to_jsonb(s);
end $$;

revoke all on function public.publish_quiz_to_batches_atomic(uuid,uuid,uuid,text,uuid[],boolean)
 from public,anon,authenticated;
grant execute on function public.publish_quiz_to_batches_atomic(uuid,uuid,uuid,text,uuid[],boolean)
 to service_role;
commit;
notify pgrst,'reload schema';
