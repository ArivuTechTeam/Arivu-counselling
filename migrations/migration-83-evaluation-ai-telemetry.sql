-- Link AI-call telemetry to handwritten evaluation jobs without reusing the
-- quiz_generation_jobs foreign key.
begin;

alter table public.api_call_logs
 add column if not exists evaluation_job_id uuid;

alter table public.api_call_logs
 drop constraint if exists api_call_logs_evaluation_job_id_fkey;
alter table public.api_call_logs
 add constraint api_call_logs_evaluation_job_id_fkey
 foreign key(evaluation_job_id) references public.evaluation_jobs(id) on delete set null;

create index if not exists api_call_logs_evaluation_job_time
 on public.api_call_logs(evaluation_job_id,created_at desc);

commit;
notify pgrst,'reload schema';
