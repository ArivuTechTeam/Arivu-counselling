-- Phase 5 foundation. Apply after the current merged schema and migration 46.
-- Additive, rerunnable, service-only RPCs. No question/attempt data is deleted.
begin;
alter table public.questions add column if not exists content_version bigint not null default 1;
alter table public.questions add column if not exists release_locked boolean not null default false;
alter table public.questions add column if not exists origin_question_id uuid references public.questions(id) on delete set null;
alter table public.questions add column if not exists source_quiz_id uuid references public.quiz_sets(id) on delete set null;
alter table public.quiz_sets add column if not exists released_at timestamptz;
alter table public.quiz_sets add column if not exists last_publication_token text;
create index if not exists questions_origin_idx on public.questions(origin_question_id) where origin_question_id is not null;
create index if not exists questions_source_quiz_idx on public.questions(source_quiz_id) where source_quiz_id is not null;

create table if not exists public.quiz_copy_requests (
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 actor_id uuid not null references public.profiles(id) on delete cascade,
 request_key uuid not null,
 source_id uuid not null,
 title text not null,
 quiz_id uuid not null references public.quiz_sets(id),
 primary key(tenant_id,actor_id,request_key)
);
create index if not exists quiz_copy_requests_actor_idx on public.quiz_copy_requests(actor_id);
create index if not exists quiz_copy_requests_quiz_idx on public.quiz_copy_requests(quiz_id);
alter table public.quiz_copy_requests enable row level security;
revoke all on public.quiz_copy_requests from public,anon,authenticated;
grant select,insert on public.quiz_copy_requests to service_role;

-- Freeze known releases, including archived quizzes with recorded attempts.
update public.quiz_sets s set released_at=coalesce(s.published_at,s.created_at)
where s.released_at is null and (s.status='published' or exists(
 select 1 from public.quiz_variants v join public.quiz_attempts a on a.variant_id=v.id where v.quiz_set_id=s.id));
update public.questions q set release_locked=true where not q.release_locked and exists(
 select 1 from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id
 join public.quiz_sets s on s.id=v.quiz_set_id where l.question_id=q.id and s.released_at is not null);

create or replace function public.guard_released_question() returns trigger
language plpgsql set search_path=public as $$
#variable_conflict use_column
begin
 if tg_op='DELETE' then
  if old.release_locked then raise exception 'quiz_locked' using errcode='PT409'; end if;
  return old;
 end if;
 -- Author/reviewer anonymization and lineage FK cleanup remain permitted.
 if old.release_locked and ((to_jsonb(new)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])
   is distinct from (to_jsonb(old)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])) then
  raise exception 'quiz_locked' using errcode='PT409';
 end if;
 new.content_version:=old.content_version+1;
 return new;
end $$;
drop trigger if exists guard_released_question on public.questions;
create trigger guard_released_question before update or delete on public.questions
 for each row execute function public.guard_released_question();

create or replace function public.guard_released_structure() returns trigger
language plpgsql set search_path=public as $$
#variable_conflict use_column
declare ids uuid[]; s record;
begin
 if tg_table_name='quiz_variants' then
  ids:=array[case when tg_op<>'INSERT' then old.quiz_set_id end,case when tg_op<>'DELETE' then new.quiz_set_id end];
 else
  select array_agg(quiz_set_id) into ids from public.quiz_variants
   where id in (case when tg_op<>'INSERT' then old.variant_id end,case when tg_op<>'DELETE' then new.variant_id end);
 end if;
 -- Lock parents also for drafts: membership cannot change during release/copy.
 for s in select id,released_at from public.quiz_sets where id=any(ids) order by id for update loop
  if s.released_at is not null then raise exception 'quiz_locked' using errcode='PT409'; end if;
 end loop;
 if tg_op='DELETE' then return old; end if;
 return new;
end $$;
drop trigger if exists guard_released_variant on public.quiz_variants;
create trigger guard_released_variant before insert or update or delete on public.quiz_variants
 for each row execute function public.guard_released_structure();
drop trigger if exists guard_released_membership on public.quiz_variant_questions;
create trigger guard_released_membership before insert or update or delete on public.quiz_variant_questions
 for each row execute function public.guard_released_structure();

create or replace function public.assert_quiz_owner(p_id uuid,p_tenant uuid,p_actor uuid) returns void
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
begin
 if not exists(select 1 from public.quiz_sets s join public.profiles p on p.id=s.created_by
  join public.tenants t on t.id=s.tenant_id
  where s.id=p_id and s.tenant_id=p_tenant and s.created_by=p_actor
   and p.tenant_id=p_tenant and p.role='teacher' and t.is_active
   and (s.subject_id is null or exists(select 1 from public.teacher_subjects ts
    where ts.subject_id=s.subject_id and ts.teacher_id=p_actor and ts.tenant_id=p_tenant))) then
  raise exception 'quiz_no_access' using errcode='PT404';
 end if;
end $$;

create or replace function public.quiz_publication_state(p_id uuid,p_tenant uuid,p_actor uuid) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare token text; locked boolean;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select md5(jsonb_build_object('subject',s.subject_id,'document',s.document_id,'status',s.status,
  'variants',coalesce((select jsonb_agg(jsonb_build_array(v.id,v.variant_type,v.time_limit_minutes) order by v.id)
    from public.quiz_variants v where v.quiz_set_id=s.id),'[]'),
  'items',coalesce((select jsonb_agg(jsonb_build_array(l.id,l.variant_id,l.question_id,l.order_index,l.marks_override,q.content_version) order by l.id)
    from public.quiz_variants v join public.quiz_variant_questions l on l.variant_id=v.id
    join public.questions q on q.id=l.question_id where v.quiz_set_id=s.id),'[]'))::text),s.released_at is not null
 into token,locked from public.quiz_sets s where s.id=p_id;
 return jsonb_build_object('publication_token',token,'release_locked',locked,'reuse_enabled',true);
end $$;

create or replace function public.publish_quiz_atomic(p_id uuid,p_tenant uuid,p_actor uuid,p_token text) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; v record; n integer; total numeric;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 perform 1 from public.questions q where q.id in(select l.question_id from public.quiz_variant_questions l
  join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id) order by q.id for update;
 if s.status='published' and p_token is not null and s.last_publication_token=p_token then return to_jsonb(s); end if;
 if p_token is null or p_token is distinct from (public.quiz_publication_state(p_id,p_tenant,p_actor)->>'publication_token') then
  raise exception 'quiz_changed' using errcode='PT409';
 end if;
 if s.status='archived' then raise exception 'quiz_restore_first' using errcode='PT409'; end if;
 if s.status='published' then return to_jsonb(s); end if;
 if not exists(select 1 from public.quiz_variants where quiz_set_id=p_id) then
  raise exception 'quiz_empty' using errcode='PT409'; end if;
 for v in select * from public.quiz_variants where quiz_set_id=p_id order by id loop
  if v.tenant_id<>p_tenant or exists(select 1 from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and (l.tenant_id<>p_tenant or q.tenant_id<>p_tenant or q.created_by is distinct from p_actor
   or q.review_status not in ('approved','rejected'))) then raise exception 'quiz_review_required' using errcode='PT409'; end if;
  select count(*),sum(coalesce(l.marks_override,q.marks)) into n,total
   from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and q.review_status='approved';
  if n=0 or total is null or exists(select 1 from public.quiz_variant_questions l join public.questions q on q.id=l.question_id
   where l.variant_id=v.id and q.review_status='approved' and coalesce(l.marks_override,q.marks)<=0) then
   raise exception 'quiz_empty' using errcode='PT409'; end if;
  if s.released_at is null then update public.quiz_variants set total_marks=total where id=v.id; end if;
 end loop;
 update public.questions set release_locked=true where not release_locked and id in(
  select l.question_id from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id);
 update public.quiz_sets set status='published',published_at=now(),released_at=coalesce(released_at,now()),last_publication_token=p_token where id=p_id returning * into s;
 insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id)
  values(p_tenant,p_actor,'teacher','quiz.published','quiz_set',p_id);
 return to_jsonb(s);
end $$;

create or replace function public.copy_quiz_draft(p_id uuid,p_tenant uuid,p_actor uuid,p_key uuid,p_title text) returns jsonb
language plpgsql security invoker set search_path=public as $$
#variable_conflict use_column
declare s public.quiz_sets; prior public.quiz_copy_requests; dest uuid:=gen_random_uuid(); nv uuid; nq uuid;
 v record; l record; q public.questions; count_items integer; payload jsonb;
begin
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 if p_key is null or length(trim(p_title)) not between 1 and 200 then raise exception 'quiz_invalid_title' using errcode='PT400'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_tenant::text||p_actor::text||p_key::text,47));
 select * into prior from public.quiz_copy_requests where tenant_id=p_tenant and actor_id=p_actor and request_key=p_key;
 if found then
  if prior.source_id<>p_id or prior.title<>p_title then raise exception 'quiz_request_conflict' using errcode='PT409'; end if;
  return jsonb_build_object('quiz_set_id',prior.quiz_id,'replayed',true);
 end if;
 select * into s from public.quiz_sets where id=p_id and tenant_id=p_tenant for update;
 perform public.assert_quiz_owner(p_id,p_tenant,p_actor);
 perform 1 from public.questions q where q.id in(select l.question_id from public.quiz_variant_questions l
  join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id) order by q.id for update;
 select count(*) into count_items from public.quiz_variant_questions l join public.quiz_variants v on v.id=l.variant_id where v.quiz_set_id=p_id;
 if count_items not between 1 and 500 then raise exception 'quiz_copy_size' using errcode='PT400'; end if;
 insert into public.quiz_sets(id,tenant_id,chapter_id,subject_id,document_id,title,description,status,created_by)
  values(dest,p_tenant,s.chapter_id,s.subject_id,s.document_id,p_title,s.description,'draft',p_actor);
 for v in select * from public.quiz_variants where quiz_set_id=p_id order by created_at,id loop
  if v.tenant_id<>p_tenant then raise exception 'quiz_no_access' using errcode='PT404'; end if;
  nv:=gen_random_uuid();
  insert into public.quiz_variants(id,tenant_id,quiz_set_id,variant_type,time_limit_minutes,total_marks)
   values(nv,p_tenant,dest,v.variant_type,v.time_limit_minutes,null);
  for l in select * from public.quiz_variant_questions where variant_id=v.id order by order_index,id loop
   select * into q from public.questions where id=l.question_id and tenant_id=p_tenant and created_by=p_actor;
   if not found or l.tenant_id<>p_tenant then raise exception 'quiz_no_access' using errcode='PT404'; end if;
   nq:=gen_random_uuid();
   -- Copy the full installed question shape, including existing figure_id and
   -- future additive fields. Reset identity and release state, never the source.
   payload:=to_jsonb(q)||jsonb_build_object('id',nq,'created_at',now(),'content_version',1,'release_locked',false,
    'origin_question_id',coalesce(q.origin_question_id,q.id),'source_quiz_id',coalesce(q.source_quiz_id,p_id));
   insert into public.questions select (jsonb_populate_record(null::public.questions,payload)).*;
   insert into public.quiz_variant_questions(tenant_id,variant_id,question_id,order_index,marks_override)
    values(p_tenant,nv,nq,l.order_index,l.marks_override);
  end loop;
 end loop;
 insert into public.quiz_copy_requests values(p_tenant,p_actor,p_key,p_id,p_title,dest);
 insert into public.events(tenant_id,actor_id,actor_role,event_type,subject_type,subject_id,metadata)
  values(p_tenant,p_actor,'teacher','quiz.duplicated','quiz_set',dest,jsonb_build_object('source_quiz_id',p_id,'question_count',count_items));
 return jsonb_build_object('quiz_set_id',dest,'replayed',false);
end $$;

revoke all on function public.guard_released_question(),public.guard_released_structure(),
 public.assert_quiz_owner(uuid,uuid,uuid),public.quiz_publication_state(uuid,uuid,uuid),
 public.publish_quiz_atomic(uuid,uuid,uuid,text),public.copy_quiz_draft(uuid,uuid,uuid,uuid,text) from public,anon,authenticated;
grant execute on function public.guard_released_question(),public.guard_released_structure(),
 public.assert_quiz_owner(uuid,uuid,uuid),public.quiz_publication_state(uuid,uuid,uuid),
 public.publish_quiz_atomic(uuid,uuid,uuid,text),public.copy_quiz_draft(uuid,uuid,uuid,uuid,text) to service_role;
commit;
notify pgrst,'reload schema';
