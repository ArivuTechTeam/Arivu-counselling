-- Generated with Supabase CLI; apply once after migrations 01-41.
begin;
alter table public.questions add column media jsonb not null default '[]'::jsonb
  check (jsonb_typeof(media)='array' and jsonb_array_length(media)<=12);
alter table public.questions add column media_version integer not null default 0;

create table public.question_assets (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  created_by uuid references public.profiles(id) on delete set null,
  -- Retain immutable assets even if the live question is removed. Attempt
  -- snapshots remain authorized references; tenant deletion still cascades.
  question_id uuid not null,
  storage_path text not null unique,
  content_hash text not null,
  width integer not null check(width between 1 and 5000),
  height integer not null check(height between 1 and 5000),
  byte_size integer not null check(byte_size between 1 and 5242880),
  provenance jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index question_assets_owner on public.question_assets(tenant_id, created_by, question_id);
create index question_assets_question on public.question_assets(question_id);
alter table public.question_assets enable row level security;
revoke all on public.question_assets from public,anon,authenticated;
grant select,insert,delete on public.question_assets to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('question-media','question-media',false,5242880,array['image/png']);
-- Even if an older installation has broad object policies, browser roles must
-- obtain question media through the authenticated application, never Storage.
create policy question_media_server_only on storage.objects as restrictive
for all to anon,authenticated
using(bucket_id <> 'question-media') with check(bucket_id <> 'question-media');

create function public.set_question_media(p_question uuid,p_tenant uuid,p_actor uuid,
 p_version integer,p_media jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare q public.questions; item jsonb; qs record;
begin
 select * into q from public.questions where id=p_question and tenant_id=p_tenant
   and created_by=p_actor for update;
 if not found then raise exception 'Question unavailable'; end if;
 if q.media_version <> p_version then raise exception 'Question media changed; reload'; end if;
 if jsonb_typeof(p_media) <> 'array' or jsonb_array_length(p_media)>12 then raise exception 'Invalid media'; end if;
 if not exists(select 1 from public.profiles where id=p_actor and tenant_id=p_tenant and role='teacher') then
   raise exception 'Teacher unavailable'; end if;
 for qs in select s.id,s.status from public.quiz_sets s where s.tenant_id=p_tenant and exists(
   select 1 from public.quiz_variants v join public.quiz_variant_questions l on l.variant_id=v.id
   where v.quiz_set_id=s.id and l.question_id=q.id and l.tenant_id=p_tenant)
   order by s.id for update loop
   if qs.status::text='published' then raise exception 'Archive the quiz before changing its visuals'; end if;
 end loop;
 for item in select * from jsonb_array_elements(p_media) loop
   if not exists(select 1 from public.question_assets a where a.id=(item->>'asset_id')::uuid
      and a.tenant_id=p_tenant and a.created_by=p_actor and a.question_id=q.id) then
      raise exception 'Image unavailable'; end if;
   if length(coalesce(item->>'alt','')) not between 1 and 500 then raise exception 'Invalid image description'; end if;
   if item->>'option_id' is not null and not exists(select 1 from jsonb_array_elements(q.options) o where o->>'id'=item->>'option_id') then
      raise exception 'Option unavailable'; end if;
 end loop;
 if p_media=q.media then return to_jsonb(q); end if;
 update public.questions set media=p_media,media_version=media_version+1,
   review_status='pending_review',reviewed_at=null,reviewed_by=null,
   verification_status='needs_teacher_review'
   where id=q.id returning * into q;
 return to_jsonb(q);
end $$;
revoke all on function public.set_question_media(uuid,uuid,uuid,integer,jsonb) from public,anon,authenticated;
grant execute on function public.set_question_media(uuid,uuid,uuid,integer,jsonb) to service_role;

-- Recheck at publication time, including publication racing an image edit.
create function public.guard_visual_quiz_publication() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
 if new.status::text='published' and exists(
  select 1 from public.quiz_variants v join public.quiz_variant_questions l on l.variant_id=v.id
  join public.questions q on q.id=l.question_id where v.quiz_set_id=new.id
    and q.tenant_id=new.tenant_id and jsonb_array_length(q.media)>0
    and q.review_status::text not in ('approved','rejected')) then
   raise exception 'Review visual questions before publishing';
 end if;
 return new;
end $$;
revoke all on function public.guard_visual_quiz_publication() from public,anon,authenticated;
grant execute on function public.guard_visual_quiz_publication() to service_role;
create trigger guard_visual_quiz_publication before update of status on public.quiz_sets
for each row execute function public.guard_visual_quiz_publication();
notify pgrst,'reload schema';
commit;
