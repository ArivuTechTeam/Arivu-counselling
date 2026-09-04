-- ============================================================================
-- Migration 05 — Self-serve practice engine (student dashboard)
-- Run this ONCE in the Supabase SQL Editor (top to bottom), like schema.sql.
--
-- WHAT THIS IS: the foundation for student-initiated practice — Smart Quiz,
-- chapter practice, exam simulator, daily challenge, challenge-a-friend and the
-- revision list. Every such mode is ONE row in `practice_sessions` over a FROZEN
-- set of question ids, graded by the same engine as teacher quizzes.
--
-- SAFE + ADDITIVE: three new tables + indexes + student-owned RLS. Nothing
-- existing changes; teacher quizzes keep using quiz_sets / quiz_attempts.
-- ============================================================================


-- ── A session = a frozen set of questions + config, taken by one student ─────
create table if not exists practice_sessions (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null references tenants(id),
  student_id   uuid not null references profiles(id),
  mode         text not null,                       -- smart / chapter / exam / daily / challenge / revision
  subject_id   uuid references subjects(id),
  chapter_id   uuid references chapters(id),
  config       jsonb not null default '{}'::jsonb,  -- {count, difficulty, time_limit, negative_marking, ...}
  question_ids jsonb not null default '[]'::jsonb,  -- FROZEN, ordered — reproducible + fair for challenges
  status       text not null default 'in_progress', -- in_progress / graded
  total_score  numeric,
  max_score    numeric,
  started_at   timestamptz not null default now(),
  submitted_at timestamptz
);
create index if not exists idx_practice_sessions_tenant  on practice_sessions(tenant_id);
create index if not exists idx_practice_sessions_student on practice_sessions(student_id);

create table if not exists practice_answers (
  id             uuid primary key default gen_random_uuid(),
  tenant_id      uuid not null references tenants(id),
  session_id     uuid not null references practice_sessions(id) on delete cascade,
  question_id    uuid not null references questions(id),
  student_answer jsonb,
  is_correct     boolean,
  marks_awarded  numeric,
  answered_at    timestamptz not null default now(),
  unique (session_id, question_id)
);
create index if not exists idx_practice_answers_session on practice_answers(session_id);

-- ── Revision list = bookmarked questions a student wants to revisit ──────────
create table if not exists bookmarks (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id),
  student_id  uuid not null references profiles(id) on delete cascade,
  question_id uuid not null references questions(id) on delete cascade,
  created_at  timestamptz not null default now(),
  unique (student_id, question_id)
);
create index if not exists idx_bookmarks_student on bookmarks(student_id);


-- ── Row Level Security: a student owns their own rows; staff/super can read ──
alter table practice_sessions enable row level security;
create policy "own practice sessions" on practice_sessions
  for all
  using      (tenant_id = current_tenant_id()
              and (student_id = auth.uid() or is_staff() or is_super_admin()))
  with check (tenant_id = current_tenant_id() and student_id = auth.uid());

alter table practice_answers enable row level security;
create policy "own practice answers" on practice_answers
  for all
  using      (tenant_id = current_tenant_id()
              and (exists (select 1 from practice_sessions s
                           where s.id = session_id and s.student_id = auth.uid())
                   or is_staff() or is_super_admin()))
  with check (tenant_id = current_tenant_id());

alter table bookmarks enable row level security;
create policy "own bookmarks" on bookmarks
  for all
  using      (tenant_id = current_tenant_id()
              and (student_id = auth.uid() or is_staff() or is_super_admin()))
  with check (tenant_id = current_tenant_id() and student_id = auth.uid());

-- (Our backend also writes via the service role, which bypasses RLS — the
--  policies above are defense-in-depth so a student can only ever touch theirs.)

-- ============================================================================
-- END OF MIGRATION 05
-- ============================================================================
