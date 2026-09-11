-- Atomic guards for Daily Challenge and Exam Simulator starts.
-- Existing rows remain nullable and continue to be discovered by application
-- fallback logic; new rows opt into the database-enforced slots below.

alter table public.practice_sessions
  add column if not exists activity_date date;

alter table public.practice_sessions
  add column if not exists active_slot boolean;

create unique index if not exists uq_practice_daily_student_date
  on public.practice_sessions (tenant_id, student_id, activity_date)
  where mode = 'daily' and activity_date is not null;

create unique index if not exists uq_practice_active_exam_student
  on public.practice_sessions (tenant_id, student_id)
  where mode = 'exam' and status = 'in_progress' and active_slot is true;
