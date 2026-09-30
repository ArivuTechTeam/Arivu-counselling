-- Phase D: mistake library, revision reconciliation, and student analytics.
begin;

create unique index if not exists uq_handwritten_question_evaluations_id_tenant
 on public.handwritten_question_evaluations(id,tenant_id);

create table if not exists public.handwritten_mistakes(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 evaluation_id uuid not null,
 question_result_id uuid,
 category text not null check(category in(
  'not_attempted','conceptual','application','presentation','calculation',
  'step_loss','keyword','format','time_management'
 )),
 severity text not null check(severity in('minor','moderate','major')),
 description text not null,
 marks_lost numeric not null check(marks_lost>0),
 suggestion text not null default '',
 chapter_name text not null,
 criterion_key text not null check(char_length(criterion_key) between 1 and 120),
 signature text not null check(signature~'^[0-9a-f]{64}$'),
 is_recurring boolean not null default false,
 created_at timestamptz not null default now(),
 constraint handwritten_mistakes_evaluation_scope_fk
  foreign key(evaluation_id,tenant_id)
  references public.handwritten_evaluations(id,tenant_id) on delete cascade,
 constraint handwritten_mistakes_question_scope_fk
  foreign key(question_result_id,tenant_id)
  references public.handwritten_question_evaluations(id,tenant_id) on delete cascade
);

create table if not exists public.handwritten_revision_items(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 subject_id uuid not null,
 chapter text not null,
 title text not null,
 description text not null default '',
 priority text not null check(priority in('high','medium','low')),
 is_resolved boolean not null default false,
 occurrence_count integer not null default 0 check(occurrence_count>=0),
 marks_at_risk numeric not null default 0 check(marks_at_risk>=0),
 source_count integer not null default 0 check(source_count>=0),
 resolution_source text not null default '' check(resolution_source in('','reviewed','improved')),
 resolved_at timestamptz,
 last_seen_at timestamptz not null default now(),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 constraint handwritten_revision_items_student_scope_fk
  foreign key(student_id,tenant_id) references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_revision_items_subject_scope_fk
  foreign key(subject_id,tenant_id) references public.subjects(id,tenant_id) on delete cascade,
 unique(tenant_id,student_id,subject_id,title)
);

create table if not exists public.handwritten_student_analytics(
 id uuid primary key default gen_random_uuid(),
 tenant_id uuid not null references public.tenants(id) on delete cascade,
 student_id uuid not null,
 subject_id uuid not null,
 total_attempts integer not null default 0 check(total_attempts>=0),
 avg_percentage numeric not null default 0,
 best_percentage numeric not null default 0,
 latest_percentage numeric not null default 0,
 score_history jsonb not null default '[]'::jsonb check(jsonb_typeof(score_history)='array'),
 current_level text not null default 'beginner' check(current_level in(
  'beginner','improving','proficient','advanced','exam_ready'
 )),
 improvement_rate numeric not null default 0,
 updated_at timestamptz not null default now(),
 constraint handwritten_student_analytics_student_scope_fk
  foreign key(student_id,tenant_id) references public.profiles(id,tenant_id) on delete cascade,
 constraint handwritten_student_analytics_subject_scope_fk
  foreign key(subject_id,tenant_id) references public.subjects(id,tenant_id) on delete cascade,
 unique(tenant_id,student_id,subject_id)
);

create index if not exists handwritten_mistakes_evaluation
 on public.handwritten_mistakes(tenant_id,evaluation_id);
create index if not exists handwritten_mistakes_signature
 on public.handwritten_mistakes(tenant_id,signature,is_recurring);
create index if not exists handwritten_revision_items_student_subject
 on public.handwritten_revision_items(tenant_id,student_id,subject_id,is_resolved);
create index if not exists handwritten_student_analytics_student
 on public.handwritten_student_analytics(tenant_id,student_id,updated_at desc);

alter table public.handwritten_mistakes enable row level security;
alter table public.handwritten_revision_items enable row level security;
alter table public.handwritten_student_analytics enable row level security;
revoke all on public.handwritten_mistakes,public.handwritten_revision_items,
 public.handwritten_student_analytics from public,anon,authenticated;
grant select,insert,update,delete on public.handwritten_mistakes,
 public.handwritten_revision_items,public.handwritten_student_analytics to service_role;

create or replace function public.replace_handwritten_mistakes(
 p_tenant uuid,p_evaluation uuid,p_rows jsonb
) returns integer language plpgsql security invoker set search_path='' as $$
declare item jsonb; inserted integer:=0;
begin
 if jsonb_typeof(p_rows)<>'array' then raise exception 'mistake rows must be an array'; end if;
 if not exists(
  select 1 from public.handwritten_evaluations e
  join public.handwritten_submissions s on s.id=e.submission_id and s.tenant_id=e.tenant_id
  where e.id=p_evaluation and e.tenant_id=p_tenant and e.status='completed'
   and s.status='evaluated'
 ) then raise exception 'evaluation is not committed for learning'; end if;
 delete from public.handwritten_mistakes where tenant_id=p_tenant and evaluation_id=p_evaluation;
 for item in select value from jsonb_array_elements(p_rows) loop
  if nullif(item->>'question_result_id','') is not null and not exists(
   select 1 from public.handwritten_question_evaluations q
   where q.id=(item->>'question_result_id')::uuid and q.tenant_id=p_tenant
    and q.evaluation_id=p_evaluation
  ) then raise exception 'question result is outside evaluation scope'; end if;
  insert into public.handwritten_mistakes(
   tenant_id,evaluation_id,question_result_id,category,severity,description,
   marks_lost,suggestion,chapter_name,criterion_key,signature
  ) values(
   p_tenant,p_evaluation,nullif(item->>'question_result_id','')::uuid,
   item->>'category',item->>'severity',item->>'description',
   (item->>'marks_lost')::numeric,coalesce(item->>'suggestion',''),
   item->>'chapter_name',item->>'criterion_key',item->>'signature'
  );
  inserted:=inserted+1;
 end loop;
 return inserted;
end $$;

create or replace function public.reconcile_handwritten_revision_items(
 p_tenant uuid,p_student uuid,p_subject uuid
) returns boolean language plpgsql security invoker set search_path='' as $$
declare topic_row record; reconciled_at timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.profiles p where p.id=p_student
  and p.tenant_id=p_tenant and p.role='student' for update) then return false; end if;
 if not exists(select 1 from public.subjects s where s.id=p_subject and s.tenant_id=p_tenant) then return false; end if;

 update public.handwritten_mistakes m set is_recurring=false
 where m.tenant_id=p_tenant and exists(
  select 1 from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.id=m.evaluation_id and hs.student_id=p_student and ep.subject_id=p_subject
 );

 with ranked as(
  select e.id evaluation_id,hs.evaluation_paper_id,
   row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
  from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
   and e.status='completed' and hs.status='evaluated'
 ), recurring as(
  select m.signature
  from public.handwritten_mistakes m join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.signature<>''
  group by m.signature having count(distinct r.evaluation_paper_id)>=2
 )
 update public.handwritten_mistakes m set is_recurring=true
 from ranked r,recurring x where r.position=1 and m.evaluation_id=r.evaluation_id
  and m.tenant_id=p_tenant and m.signature=x.signature;

 for topic_row in
  with ranked as(
   select e.id evaluation_id,hs.evaluation_paper_id,
    row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
   from public.handwritten_evaluations e
   join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
   join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
   where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
    and e.status='completed' and hs.status='evaluated'
  )
  select m.chapter_name,round(sum(m.marks_lost),1) marks,
   count(distinct r.evaluation_paper_id)::integer paper_count,
   (array_agg(coalesce(nullif(m.suggestion,''),m.description)
    order by m.marks_lost desc,m.created_at desc))[1] description
  from public.handwritten_mistakes m join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.chapter_name<>''
  group by m.chapter_name
 loop
  insert into public.handwritten_revision_items(
   tenant_id,student_id,subject_id,chapter,title,description,priority,
   is_resolved,occurrence_count,marks_at_risk,source_count,resolution_source,
   resolved_at,last_seen_at,updated_at
  ) values(
   p_tenant,p_student,p_subject,topic_row.chapter_name,left(topic_row.chapter_name,300),
   left(coalesce(topic_row.description,''),1000),
   case when topic_row.marks>=3 or topic_row.paper_count>=3 then 'high'
    when topic_row.marks>=1 or topic_row.paper_count>=2 then 'medium' else 'low' end,
   false,topic_row.paper_count,topic_row.marks,topic_row.paper_count,'',null,reconciled_at,reconciled_at
  ) on conflict(tenant_id,student_id,subject_id,title) do update set
   chapter=excluded.chapter,description=excluded.description,priority=excluded.priority,
   is_resolved=false,occurrence_count=excluded.occurrence_count,
   marks_at_risk=excluded.marks_at_risk,source_count=excluded.source_count,
   resolution_source='',resolved_at=null,last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at;
 end loop;

 with ranked as(
  select e.id evaluation_id,hs.evaluation_paper_id,
   row_number() over(partition by hs.evaluation_paper_id order by hs.created_at desc,hs.id desc) position
  from public.handwritten_evaluations e
  join public.handwritten_submissions hs on hs.id=e.submission_id and hs.tenant_id=e.tenant_id
  join public.evaluation_papers ep on ep.id=hs.evaluation_paper_id and ep.tenant_id=hs.tenant_id
  where e.tenant_id=p_tenant and hs.student_id=p_student and ep.subject_id=p_subject
   and e.status='completed' and hs.status='evaluated'
 ), desired as(
  select distinct m.chapter_name from public.handwritten_mistakes m
  join ranked r on r.evaluation_id=m.evaluation_id and r.position=1
  where m.tenant_id=p_tenant and m.chapter_name<>''
 )
 update public.handwritten_revision_items ri set is_resolved=true,
  resolution_source='improved',resolved_at=reconciled_at,marks_at_risk=0,updated_at=reconciled_at
 where ri.tenant_id=p_tenant and ri.student_id=p_student and ri.subject_id=p_subject
  and not ri.is_resolved and not exists(select 1 from desired d where left(d.chapter_name,300)=ri.title);
 return true;
end $$;

revoke all on function public.replace_handwritten_mistakes(uuid,uuid,jsonb),
 public.reconcile_handwritten_revision_items(uuid,uuid,uuid)
 from public,anon,authenticated;
grant execute on function public.replace_handwritten_mistakes(uuid,uuid,jsonb),
 public.reconcile_handwritten_revision_items(uuid,uuid,uuid) to service_role;

commit;
notify pgrst,'reload schema';
