-- Migration 60 — private, tenant-scoped student feedback and support requests.
-- Apply after migration 59, before deploying the contact API.
begin;

create table public.student_contact_requests (
  id uuid primary key default gen_random_uuid(),
  reference text not null unique check (reference ~ '^[0-9A-F]{12}$'),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  student_id uuid not null,
  kind text not null check (kind in ('feedback', 'support')),
  category text not null check (category in ('general', 'feature_idea', 'course_access', 'quiz_issue', 'app_bug')),
  routed_to text not null check (routed_to in ('platform', 'institution')),
  message text not null check (char_length(btrim(message)) between 10 and 4000),
  rating smallint check (rating between 1 and 5),
  status text not null default 'open' check (status in ('open', 'answered', 'closed')),
  reply text check (reply is null or char_length(btrim(reply)) between 1 and 4000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint student_contact_requests_student_tenant_fkey
    foreign key (student_id, tenant_id) references public.profiles(id, tenant_id)
    on delete cascade,
  constraint student_contact_requests_route_check check (
    (kind = 'feedback' and category in ('general', 'feature_idea', 'app_bug')
      and routed_to = 'platform')
    or (kind = 'support' and category in ('course_access', 'quiz_issue')
      and routed_to = 'institution' and rating is null)
    or (kind = 'support' and category = 'app_bug'
      and routed_to = 'platform' and rating is null)
  )
);

create index student_contact_requests_student_recent_idx
  on public.student_contact_requests (tenant_id, student_id, created_at desc);
create index student_contact_requests_inbox_idx
  on public.student_contact_requests (routed_to, tenant_id, created_at desc);

-- Browser clients cannot access ticket bodies directly. Every operation is
-- authenticated and role/tenant-filtered by the backend before service-role use.
alter table public.student_contact_requests enable row level security;
revoke all on table public.student_contact_requests from public, anon, authenticated;
grant select, insert, update, delete on table public.student_contact_requests to service_role;

commit;
notify pgrst, 'reload schema';
