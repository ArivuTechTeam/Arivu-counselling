// Isolated PostgreSQL contract/security checks for migration 69.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration = fs.readFileSync("migrations/migration-69-cursor-pagination.sql", "utf8");

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create table public.tenants (id uuid primary key);
  create table public.profiles (id uuid primary key, tenant_id uuid not null, role text not null, full_name text);
  create table public.courses (id uuid primary key, tenant_id uuid not null, name text not null);
  create table public.subjects (id uuid primary key, tenant_id uuid not null, course_id uuid not null, course_level_id uuid, name text not null);
  create table public.teacher_subjects (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, teacher_id uuid not null, subject_id uuid not null);
  create table public.chapters (id uuid primary key, tenant_id uuid not null, subject_id uuid not null, name text not null);
  create table public.documents (id uuid primary key, tenant_id uuid not null, uploaded_by uuid, created_at timestamptz not null default now());
  create table public.quiz_sets (
    id uuid primary key, tenant_id uuid not null, subject_id uuid, chapter_id uuid,
    title text not null, status text not null, created_by uuid,
    created_at timestamptz not null, published_at timestamptz,
    audience_mode text not null default 'legacy_course'
  );
  create table public.quiz_variants (
    id uuid primary key, tenant_id uuid not null, quiz_set_id uuid not null,
    variant_type text not null, total_marks numeric, time_limit_minutes numeric
  );
  create table public.questions (id uuid primary key, tenant_id uuid not null, type text not null, review_status text not null);
  create table public.quiz_variant_questions (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, variant_id uuid not null, question_id uuid not null);
  create table public.quiz_attempts (
    id uuid primary key, tenant_id uuid not null, variant_id uuid not null,
    student_id uuid not null, status text not null, total_score numeric,
    submitted_at timestamptz
  );
  create table public.practice_sessions (
    id uuid primary key, tenant_id uuid not null, student_id uuid not null,
    mode text not null, subject_id uuid, chapter_id uuid, status text not null,
    total_score numeric, max_score numeric, submitted_at timestamptz
  );
  create table public.enrollments (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    profile_id uuid not null, course_id uuid not null, course_level_id uuid
  );
  create table public.batch_memberships (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, batch_id uuid not null, profile_id uuid not null, active boolean not null default true, valid_from date, valid_to date);
  create table public.quiz_assignments (id uuid primary key default gen_random_uuid(), tenant_id uuid not null, quiz_set_id uuid not null, batch_id uuid not null, status text not null, available_from timestamptz, available_to timestamptz);
`);

await db.exec(migration);
await db.exec(migration);

const ids = {
  tenant: "00000000-0000-4000-8000-000000000001",
  otherTenant: "00000000-0000-4000-8000-000000000002",
  teacher: "00000000-0000-4000-8000-000000000010",
  student: "00000000-0000-4000-8000-000000000020",
  otherStudent: "00000000-0000-4000-8000-000000000021",
  course: "00000000-0000-4000-8000-000000000030",
  subject: "00000000-0000-4000-8000-000000000040",
  chapter: "00000000-0000-4000-8000-000000000050",
  quiz1: "00000000-0000-4000-8000-000000000061",
  quiz2: "00000000-0000-4000-8000-000000000062",
  quiz3: "00000000-0000-4000-8000-000000000063",
  variant1: "00000000-0000-4000-8000-000000000071",
  variant2: "00000000-0000-4000-8000-000000000072",
  variant3: "00000000-0000-4000-8000-000000000073",
  attempt1: "00000000-0000-4000-8000-000000000081",
  attempt2: "00000000-0000-4000-8000-000000000082",
  practice: "00000000-0000-4000-8000-000000000091",
  question: "00000000-0000-4000-8000-0000000000a1",
};

await db.query("insert into tenants(id) values($1),($2)", [ids.tenant, ids.otherTenant]);
await db.query(`insert into profiles(id,tenant_id,role,full_name) values
  ($1,$2,'teacher','Teacher'),($3,$2,'student','Student'),($4,$5,'student','Other')`,
  [ids.teacher, ids.tenant, ids.student, ids.otherStudent, ids.otherTenant]);
await db.query("insert into courses(id,tenant_id,name) values($1,$2,'Course')", [ids.course, ids.tenant]);
await db.query("insert into subjects(id,tenant_id,course_id,name) values($1,$2,$3,'Math')", [ids.subject, ids.tenant, ids.course]);
await db.query("insert into chapters(id,tenant_id,subject_id,name) values($1,$2,$3,'Algebra')", [ids.chapter, ids.tenant, ids.subject]);
await db.query("insert into teacher_subjects(tenant_id,teacher_id,subject_id) values($1,$2,$3)", [ids.tenant, ids.teacher, ids.subject]);
await db.query("insert into enrollments(tenant_id,profile_id,course_id) values($1,$2,$3)", [ids.tenant, ids.student, ids.course]);
await db.query(`insert into quiz_sets(id,tenant_id,subject_id,chapter_id,title,status,created_by,created_at,published_at) values
  ($1,$2,$3,$4,'Newest','published',$5,'2026-09-25T12:00:00Z','2026-09-25T12:00:00Z'),
  ($6,$2,$3,$4,'Middle','published',$5,'2026-09-25T11:00:00Z','2026-09-25T11:00:00Z'),
  ($7,$2,$3,$4,'Oldest','published',$5,'2026-09-25T10:00:00Z','2026-09-25T10:00:00Z')`,
  [ids.quiz1, ids.tenant, ids.subject, ids.chapter, ids.teacher, ids.quiz2, ids.quiz3]);
await db.query(`insert into quiz_variants(id,tenant_id,quiz_set_id,variant_type,total_marks) values
  ($1,$2,$3,'mixed',10),($4,$2,$5,'mixed',10),($6,$2,$7,'mixed',10)`,
  [ids.variant1, ids.tenant, ids.quiz1, ids.variant2, ids.quiz2, ids.variant3, ids.quiz3]);
await db.query("insert into questions(id,tenant_id,type,review_status) values($1,$2,'mcq_single','approved')", [ids.question, ids.tenant]);
await db.query(`insert into quiz_variant_questions(tenant_id,variant_id,question_id) values
  ($1,$2,$5),($1,$3,$5),($1,$4,$5)`, [ids.tenant, ids.variant1, ids.variant2, ids.variant3, ids.question]);
await db.query(`insert into quiz_attempts(id,tenant_id,variant_id,student_id,status,total_score,submitted_at) values
  ($1,$2,$3,$4,'graded',8,'2026-09-25T12:30:00Z'),
  ($5,$2,$6,$4,'graded',7,'2026-09-25T11:30:00Z')`,
  [ids.attempt1, ids.tenant, ids.variant1, ids.student, ids.attempt2, ids.variant2]);
await db.query(`insert into practice_sessions(id,tenant_id,student_id,mode,subject_id,chapter_id,status,total_score,max_score,submitted_at)
  values($1,$2,$3,'smart',$4,$5,'graded',4,5,'2026-09-25T10:30:00Z')`,
  [ids.practice, ids.tenant, ids.student, ids.subject, ids.chapter]);

const teacherPage = async (beforeAt = null, beforeId = null) => (
  await db.query(`select public.teacher_published_quiz_metrics_page(
    $1::uuid,$2::uuid,$3::integer,$4::timestamptz,$5::uuid,$6::uuid,$7::text
  ) as value`, [ids.tenant, ids.teacher, 2, beforeAt, beforeId, null, null])
).rows[0].value;

const first = await teacherPage();
assert.deepEqual(first.quizzes.map(row => row.id), [ids.quiz1, ids.quiz2]);
const second = await teacherPage(first.quizzes[1]._cursor_at, first.quizzes[1].id);
assert.deepEqual(second.quizzes.map(row => row.id), [ids.quiz3]);
assert.deepEqual((await teacherPage("2026-09-25T10:00:00Z", ids.quiz3)).quizzes, []);

const history = (await db.query(`select public.student_attempt_history_page(
  $1::uuid,$2::uuid,10,null,null,'all',$3::uuid,null
) as value`, [ids.tenant, ids.student, ids.subject])).rows[0].value;
assert.deepEqual(history.map(row => row.attempt_id), [ids.attempt1, ids.attempt2, ids.practice]);
const isolated = (await db.query(`select public.student_attempt_history_page(
  $1::uuid,$2::uuid,10,null,null,'all',null,null
) as value`, [ids.tenant, ids.otherStudent])).rows[0].value;
assert.deepEqual(isolated, []);

const catalog = (await db.query(`select public.student_quiz_catalog_page(
  $1::uuid,$2::uuid,2,4,false,null,null,null,null,'all',null
) as value`, [ids.tenant, ids.student])).rows[0].value;
assert.deepEqual(catalog.map(row => row.id), [ids.quiz1, ids.quiz2]);
assert.equal(catalog[0].variants[0].question_count, 1);
assert.equal(catalog[0].variants[0].attempt_count, 1);

for (const signature of [
  "public.teacher_published_quiz_metrics_page(uuid,uuid,integer,timestamp with time zone,uuid,uuid,text)",
  "public.student_attempt_history_page(uuid,uuid,integer,timestamp with time zone,uuid,text,uuid,uuid)",
  "public.student_quiz_catalog_page(uuid,uuid,integer,integer,boolean,timestamp with time zone,uuid,uuid,uuid,text,text)",
]) {
  assert.equal((await db.query("select has_function_privilege('anon',$1,'EXECUTE') allowed", [signature])).rows[0].allowed, false);
  assert.equal((await db.query("select has_function_privilege('authenticated',$1,'EXECUTE') allowed", [signature])).rows[0].allowed, false);
  assert.equal((await db.query("select has_function_privilege('service_role',$1,'EXECUTE') allowed", [signature])).rows[0].allowed, true);
}

for (const index of [
  "idx_quizsets_tenant_creator_status_created_id",
  "idx_quizsets_tenant_subject_status_created_id",
  "idx_quizsets_tenant_creator_status_published_id",
  "idx_quizsets_tenant_subject_status_published_id",
  "idx_documents_tenant_uploader_created_id",
  "idx_attempts_tenant_student_status_submitted_id",
  "idx_practice_tenant_student_status_submitted_id",
]) {
  const exists = await db.query("select to_regclass('public.' || $1) is not null as found", [index]);
  assert.equal(exists.rows[0].found, true, index);
}

console.log("migration 69 cursor pagination checks passed");
await db.close();
