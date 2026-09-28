// Isolated PostgreSQL execution check for the Release A7 post-load audit.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const report = fs.readFileSync("scripts/a7-integrity-report.sql", "utf8");

await db.exec(`
  create table public.quiz_attempts (
    id uuid primary key, tenant_id uuid not null, status text not null,
    started_at timestamptz not null, question_snapshot jsonb not null
  );
  create table public.attempt_answers (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    attempt_id uuid not null references public.quiz_attempts(id), question_id uuid not null
  );
  create table public.practice_sessions (
    id uuid primary key, tenant_id uuid not null, status text not null,
    started_at timestamptz not null, question_snapshot jsonb not null
  );
  create table public.practice_answers (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    session_id uuid not null references public.practice_sessions(id), question_id uuid not null
  );
  create table public.faculty_jobs (
    id uuid primary key, status text not null, created_at timestamptz not null,
    lease_expires_at timestamptz
  );
`);

const tenant = "00000000-0000-4000-8000-000000000001";
const otherTenant = "00000000-0000-4000-8000-000000000002";
const attempt = "00000000-0000-4000-8000-000000000010";
const session = "00000000-0000-4000-8000-000000000020";
const question = "00000000-0000-4000-8000-000000000030";
await db.query(
  "insert into quiz_attempts values($1,$2,'graded',now(),'[{\"id\":\"q\"}]')",
  [attempt, tenant],
);
await db.query(
  "insert into attempt_answers(tenant_id,attempt_id,question_id) values($1,$2,$3)",
  [tenant, attempt, question],
);
await db.query(
  "insert into practice_sessions values($1,$2,'graded',now(),'[{\"id\":\"q\"}]')",
  [session, tenant],
);
await db.query(
  "insert into practice_answers(tenant_id,session_id,question_id) values($1,$2,$3)",
  [tenant, session, question],
);

await db.exec("set arivupro.capacity_started_at = '2026-01-01T00:00:00Z'");
const healthyResults = await db.exec(report);
const healthyViolations = healthyResults.find((result) =>
  result.fields?.some((field) => field.name === "check_name")
);
assert.ok(healthyViolations, "integrity report must return the violation grid");
assert.equal(healthyViolations.rows.every((row) => Number(row.violations) === 0), true);

await db.query(
  "update attempt_answers set tenant_id=$1 where attempt_id=$2",
  [otherTenant, attempt],
);
await db.exec("set arivupro.capacity_started_at = '2026-01-01T00:00:00Z'");
const corruptResults = await db.exec(report);
const corruptViolations = corruptResults.find((result) =>
  result.fields?.some((field) => field.name === "check_name")
);
const crossTenant = corruptViolations.rows.find(
  (row) => row.check_name === "cross_tenant_quiz_answers"
);
assert.equal(Number(crossTenant.violations), 1);

console.log("A7 integrity report execution and corruption detection passed");
await db.close();
