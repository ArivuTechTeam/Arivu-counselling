-- Migration 66: durable, private paper-bank attempts.
-- Apply after migration 65 and before deploying the paper-attempt API.
begin;

create table public.paper_attempts (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references public.tenants(id) on delete cascade,
  student_id uuid not null references public.profiles(id) on delete cascade,
  paper_type text not null check (paper_type in ('pyq', 'mtp', 'rtp')),
  subject_id uuid not null,
  question_snapshot jsonb not null check (jsonb_typeof(question_snapshot) = 'array'),
  status text not null default 'in_progress' check (status in ('in_progress', 'graded')),
  result jsonb,
  started_at timestamptz not null default now(),
  submitted_at timestamptz,
  constraint paper_attempts_subject_tenant_fk foreign key (subject_id, tenant_id)
    references public.subjects(id, tenant_id) on delete cascade,
  constraint paper_attempts_result_state check (
    (status = 'in_progress' and result is null and submitted_at is null)
    or (status = 'graded' and result is not null and submitted_at is not null)
  )
);
create index paper_attempts_student_recent
  on public.paper_attempts (tenant_id, student_id, started_at desc);

-- Snapshots contain answer keys and submitted work. Only the trusted API may
-- access them; the student receives answer-stripped questions until grading.
alter table public.paper_attempts enable row level security;
revoke all on public.paper_attempts from public, anon, authenticated;
grant select, insert, update, delete on public.paper_attempts to service_role;

commit;
notify pgrst, 'reload schema';
