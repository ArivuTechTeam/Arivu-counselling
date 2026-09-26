// Isolated PostgreSQL index-contract and before/after plan checks for migration 71.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration = fs.readFileSync(
  "migrations/migration-71-query-plan-indexes.sql",
  "utf8",
);

await db.exec(`
  create table public.questions (
    id uuid primary key,
    tenant_id uuid not null
  );
  create table public.quiz_attempts (
    id uuid primary key,
    tenant_id uuid not null
  );
  create table public.practice_sessions (
    id uuid primary key,
    tenant_id uuid not null
  );
  create table public.attempt_answers (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    attempt_id uuid not null references public.quiz_attempts(id) on delete cascade,
    question_id uuid not null references public.questions(id),
    unique(attempt_id, question_id)
  );
  create table public.practice_answers (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null,
    session_id uuid not null references public.practice_sessions(id) on delete cascade,
    question_id uuid not null references public.questions(id),
    unique(session_id, question_id)
  );
  create index idx_answers_tenant on public.attempt_answers(tenant_id);
  create index idx_answers_attempt on public.attempt_answers(attempt_id);
  create index idx_practice_answers_session on public.practice_answers(session_id);
`);

const tenant = "00000000-0000-4000-8000-000000000001";
const otherTenant = "00000000-0000-4000-8000-000000000010";
const targetQuestion = "00000000-0000-4000-8000-000000000002";
const targetAttempt = "00000000-0000-4000-8000-000000000003";
const targetSession = "00000000-0000-4000-8000-000000000004";
const otherAttempt = "00000000-0000-4000-8000-000000000011";
const otherSession = "00000000-0000-4000-8000-000000000012";

await db.query(
  `insert into public.questions(id, tenant_id)
   select md5('question-' || value)::uuid, $1::uuid
   from generate_series(1, 20000) value
   union all select $2::uuid, $1::uuid`,
  [tenant, targetQuestion],
);
await db.query(
  `insert into public.quiz_attempts(id, tenant_id)
   select md5('attempt-' || value)::uuid, $1::uuid
   from generate_series(1, 20000) value
   union all select $2::uuid, $1::uuid
   union all select $3::uuid, $4::uuid`,
  [tenant, targetAttempt, otherAttempt, otherTenant],
);
await db.query(
  `insert into public.practice_sessions(id, tenant_id)
   select md5('session-' || value)::uuid, $1::uuid
   from generate_series(1, 20000) value
   union all select $2::uuid, $1::uuid
   union all select $3::uuid, $4::uuid`,
  [tenant, targetSession, otherSession, otherTenant],
);
await db.query(
  `insert into public.attempt_answers(tenant_id, attempt_id, question_id)
   select $1::uuid, md5('attempt-' || value)::uuid,
     md5('question-' || value)::uuid
   from generate_series(1, 20000) value
   union all select $1::uuid, $2::uuid, $3::uuid
   union all select $4::uuid, $5::uuid, $3::uuid`,
  [tenant, targetAttempt, targetQuestion, otherTenant, otherAttempt],
);
await db.query(
  `insert into public.practice_answers(tenant_id, session_id, question_id)
   select $1::uuid, md5('session-' || value)::uuid,
     md5('question-' || value)::uuid
   from generate_series(1, 20000) value
   union all select $1::uuid, $2::uuid, $3::uuid
   union all select $4::uuid, $5::uuid, $3::uuid`,
  [tenant, targetSession, targetQuestion, otherTenant, otherSession],
);
await db.exec("analyze public.attempt_answers; analyze public.practice_answers;");

const indexCount = async (table) => Number((await db.query(
  `select count(*)::int as count
   from pg_indexes where schemaname = 'public' and tablename = $1`,
  [table],
)).rows[0].count);
const beforeIndexCounts = {
  attempt: await indexCount("attempt_answers"),
  practice: await indexCount("practice_answers"),
};

const explain = async (table, selectedColumn) => {
  const result = await db.query(
    `explain (analyze, buffers, format text)
     select ${selectedColumn}
     from public.${table}
     where question_id = $1::uuid and tenant_id = $2::uuid`,
    [targetQuestion, tenant],
  );
  return result.rows.map((row) => row["QUERY PLAN"]).join("\n");
};

const beforeAttempt = await explain("attempt_answers", "attempt_id");
const beforePractice = await explain("practice_answers", "session_id");
assert.doesNotMatch(beforeAttempt, /idx_attempt_answers_question_tenant_attempt/);
assert.doesNotMatch(beforePractice, /idx_practice_answers_question_tenant_session/);

await db.exec(migration);
await db.exec(migration);
await db.exec("analyze public.attempt_answers; analyze public.practice_answers;");

const afterAttempt = await explain("attempt_answers", "attempt_id");
const afterPractice = await explain("practice_answers", "session_id");
assert.match(afterAttempt, /idx_attempt_answers_question_tenant_attempt/);
assert.match(afterPractice, /idx_practice_answers_question_tenant_session/);

for (const index of [
  "idx_attempt_answers_question_tenant_attempt",
  "idx_practice_answers_question_tenant_session",
]) {
  const exists = await db.query(
    "select to_regclass('public.' || $1) is not null as found",
    [index],
  );
  assert.equal(exists.rows[0].found, true, index);
}
const addedDefinitions = await db.query(`
  select indexname, indexdef from pg_indexes
  where schemaname = 'public'
    and indexname in (
      'idx_attempt_answers_question_tenant_attempt',
      'idx_practice_answers_question_tenant_session'
    )
`);
const definitions = Object.fromEntries(
  addedDefinitions.rows.map((row) => [row.indexname, row.indexdef]),
);
assert.match(
  definitions.idx_attempt_answers_question_tenant_attempt,
  /\(question_id, tenant_id\) INCLUDE \(attempt_id\)/,
);
assert.match(
  definitions.idx_practice_answers_question_tenant_session,
  /\(question_id, tenant_id\) INCLUDE \(session_id\)/,
);
for (const index of ["idx_answers_attempt", "idx_practice_answers_session"]) {
  const exists = await db.query(
    "select to_regclass('public.' || $1) is not null as found",
    [index],
  );
  assert.equal(exists.rows[0].found, false, index);
}

const uniqueIndexes = await db.query(`
  select indexdef from pg_indexes
  where schemaname = 'public'
    and tablename in ('attempt_answers', 'practice_answers')
    and indexdef like 'CREATE UNIQUE INDEX%'
`);
assert.equal(uniqueIndexes.rows.length, 4);
assert.deepEqual(
  {
    attempt: await indexCount("attempt_answers"),
    practice: await indexCount("practice_answers"),
  },
  beforeIndexCounts,
);

const attemptRows = await db.query(
  `select attempt_id from public.attempt_answers
   where question_id = $1::uuid and tenant_id = $2::uuid`,
  [targetQuestion, tenant],
);
const practiceRows = await db.query(
  `select session_id from public.practice_answers
   where question_id = $1::uuid and tenant_id = $2::uuid`,
  [targetQuestion, tenant],
);
assert.deepEqual(attemptRows.rows, [{ attempt_id: targetAttempt }]);
assert.deepEqual(practiceRows.rows, [{ session_id: targetSession }]);

console.log("migration 71 query-plan index checks passed");
console.log("attempt_answers before:\n" + beforeAttempt);
console.log("attempt_answers after:\n" + afterAttempt);
console.log("practice_answers before:\n" + beforePractice);
console.log("practice_answers after:\n" + afterPractice);
await db.close();
