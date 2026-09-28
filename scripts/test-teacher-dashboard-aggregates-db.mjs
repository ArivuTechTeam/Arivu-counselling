// Isolated PostgreSQL contract/security checks for migration 68.
// No hosted database, network connection, credential, or real user is used.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration = fs.readFileSync(
  "migrations/migration-68-teacher-dashboard-aggregates.sql",
  "utf8",
);
const explainScript = fs.readFileSync("scripts/teacher-dashboard-explain.sql", "utf8");

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create type public.user_role as enum ('super_admin','institution_admin','teacher','student');
  create type public.question_type as enum ('mcq_single');
  create type public.question_source as enum ('manual');
  create type public.review_status as enum ('pending_review','approved','rejected','needs_edit');
  create type public.variant_type as enum ('theory');
  create type public.quiz_status as enum ('draft','published','archived');
  create type public.attempt_status as enum ('in_progress','submitted','graded','abandoned');

  create table public.tenants (id uuid primary key, name text not null);
  create table public.profiles (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    role public.user_role not null, full_name text
  );
  create table public.courses (
    id uuid primary key, tenant_id uuid not null references public.tenants(id), name text not null
  );
  create table public.course_levels (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id), name text not null
  );
  create table public.subjects (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id), course_level_id uuid,
    name text not null
  );
  create table public.teacher_subjects (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    teacher_id uuid not null, subject_id uuid not null,
    unique (teacher_id, subject_id)
  );
  create table public.chapters (
    id uuid primary key, tenant_id uuid not null, subject_id uuid not null,
    name text not null, order_index int not null
  );
  create table public.documents (
    id uuid primary key, tenant_id uuid not null, uploaded_by uuid
  );
  create table public.questions (
    id uuid primary key, tenant_id uuid not null, chapter_id uuid,
    type public.question_type not null default 'mcq_single',
    source public.question_source not null default 'manual',
    review_status public.review_status not null, created_by uuid
  );
  create table public.quiz_sets (
    id uuid primary key, tenant_id uuid not null, chapter_id uuid, subject_id uuid,
    title text not null, status public.quiz_status not null, created_by uuid,
    published_at timestamptz
  );
  create table public.quiz_variants (
    id uuid primary key, tenant_id uuid not null, quiz_set_id uuid not null,
    variant_type public.variant_type not null default 'theory', total_marks numeric
  );
  create table public.quiz_variant_questions (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    variant_id uuid not null, question_id uuid not null
  );
  create table public.quiz_attempts (
    id uuid primary key, tenant_id uuid not null, variant_id uuid not null,
    student_id uuid not null, status public.attempt_status not null,
    total_score numeric, submitted_at timestamptz
  );
  create table public.enrollments (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    profile_id uuid not null, course_id uuid not null
  );

  create index idx_teacher_subjects_tenant_teacher_subject
    on public.teacher_subjects(tenant_id, teacher_id, subject_id);
  create index idx_chapters_tenant_subject on public.chapters(tenant_id, subject_id);
  create index idx_documents_tenant_uploader_created on public.documents(tenant_id, uploaded_by);
  create index idx_questions_tenant_creator_chapter on public.questions(tenant_id, created_by, chapter_id);
  create index idx_quizsets_tenant_creator_status on public.quiz_sets(tenant_id, created_by, status);
  create index idx_variants_tenant_quizset on public.quiz_variants(tenant_id, quiz_set_id);
  create index idx_vq_tenant_variant on public.quiz_variant_questions(tenant_id, variant_id);
  create index idx_attempts_tenant_variant_status on public.quiz_attempts(tenant_id, variant_id, status);
  create index idx_enrollments_tenant_course_profile on public.enrollments(tenant_id, course_id, profile_id);
`);

await db.exec(migration);
await db.exec(migration); // create-or-replace migration remains repeatable.

const ids = {
  tenant: "00000000-0000-4000-8000-000000000001",
  otherTenant: "00000000-0000-4000-8000-000000000002",
  teacher: "00000000-0000-4000-8000-000000000010",
  otherTeacher: "00000000-0000-4000-8000-000000000011",
  student1: "00000000-0000-4000-8000-000000000020",
  student2: "00000000-0000-4000-8000-000000000021",
  course: "00000000-0000-4000-8000-000000000030",
  otherCourse: "00000000-0000-4000-8000-000000000031",
  level: "00000000-0000-4000-8000-000000000040",
  otherLevel: "00000000-0000-4000-8000-000000000041",
  subject: "00000000-0000-4000-8000-000000000050",
  formerSubject: "00000000-0000-4000-8000-000000000051",
  otherSubject: "00000000-0000-4000-8000-000000000052",
  chapter: "00000000-0000-4000-8000-000000000060",
  formerChapter: "00000000-0000-4000-8000-000000000061",
  quiz1: "00000000-0000-4000-8000-000000000070",
  quiz2: "00000000-0000-4000-8000-000000000071",
  formerQuiz: "00000000-0000-4000-8000-000000000072",
  variant1: "00000000-0000-4000-8000-000000000080",
  variant2: "00000000-0000-4000-8000-000000000081",
  formerVariant: "00000000-0000-4000-8000-000000000082",
  question1: "00000000-0000-4000-8000-000000000090",
  question2: "00000000-0000-4000-8000-000000000091",
  question3: "00000000-0000-4000-8000-000000000092",
};

await db.query("insert into tenants(id,name) values($1,'Tenant'),($2,'Other tenant')", [ids.tenant, ids.otherTenant]);
await db.query(`
  insert into profiles(id,tenant_id,role,full_name) values
    ($1,$2,'teacher','Teacher One'),
    ($3,$2,'teacher','Teacher Two'),
    ($4,$2,'student','Asha Rao'),
    ($5,$2,'student','Ben Shah')
`, [ids.teacher, ids.tenant, ids.otherTeacher, ids.student1, ids.student2]);
await db.query("insert into courses(id,tenant_id,name) values($1,$2,'CA'),($3,$4,'Other')", [ids.course, ids.tenant, ids.otherCourse, ids.otherTenant]);
await db.query("insert into course_levels(id,tenant_id,course_id,name) values($1,$2,$3,'Foundation'),($4,$5,$6,'Other')", [ids.level, ids.tenant, ids.course, ids.otherLevel, ids.otherTenant, ids.otherCourse]);
await db.query(`
  insert into subjects(id,tenant_id,course_id,course_level_id,name) values
    ($1,$2,$3,$4,'Accounting'),
    ($5,$2,$3,$4,'Former subject'),
    ($6,$7,$8,$9,'Other subject')
`, [ids.subject, ids.tenant, ids.course, ids.level, ids.formerSubject, ids.otherSubject, ids.otherTenant, ids.otherCourse, ids.otherLevel]);
await db.query("insert into teacher_subjects(tenant_id,teacher_id,subject_id) values($1,$2,$3)", [ids.tenant, ids.teacher, ids.subject]);
await db.query("insert into chapters(id,tenant_id,subject_id,name,order_index) values($1,$2,$3,'Basics',1),($4,$2,$5,'Old',1)", [ids.chapter, ids.tenant, ids.subject, ids.formerChapter, ids.formerSubject]);
await db.query("insert into documents(id,tenant_id,uploaded_by) values(gen_random_uuid(),$1,$2)", [ids.tenant, ids.teacher]);
await db.query(`
  insert into questions(id,tenant_id,chapter_id,review_status,created_by) values
    ($1,$2,$3,'pending_review',$4),
    ($5,$2,$3,'approved',$4),
    ($6,$2,$3,'approved',$7)
`, [ids.question1, ids.tenant, ids.chapter, ids.teacher, ids.question2, ids.question3, ids.otherTeacher]);
await db.query(`
  insert into quiz_sets(id,tenant_id,chapter_id,subject_id,title,status,created_by,published_at) values
    ($1,$2,$3,$4,'Published','published',$5,now()),
    ($6,$2,$3,$4,'Draft','draft',$5,null),
    ($7,$2,$8,$9,'Former','published',$5,now())
`, [ids.quiz1, ids.tenant, ids.chapter, ids.subject, ids.teacher, ids.quiz2, ids.formerQuiz, ids.formerChapter, ids.formerSubject]);
await db.query(`
  insert into quiz_variants(id,tenant_id,quiz_set_id,total_marks) values
    ($1,$2,$3,10),($4,$2,$5,20),($6,$2,$7,10)
`, [ids.variant1, ids.tenant, ids.quiz1, ids.variant2, ids.quiz2, ids.formerVariant, ids.formerQuiz]);
await db.query("insert into quiz_variant_questions(tenant_id,variant_id,question_id) values($1,$2,$3),($1,$2,$4)", [ids.tenant, ids.variant1, ids.question1, ids.question2]);
await db.query(`
  insert into quiz_attempts(id,tenant_id,variant_id,student_id,status,total_score,submitted_at) values
    (gen_random_uuid(),$1,$2,$3,'graded',7,now()),
    (gen_random_uuid(),$1,$2,$4,'graded',10,now()),
    (gen_random_uuid(),$1,$2,$3,'in_progress',null,null),
    (gen_random_uuid(),$1,$5,$3,'graded',19,now()),
    (gen_random_uuid(),$1,$6,$3,'graded',10,now())
`, [ids.tenant, ids.variant1, ids.student1, ids.student2, ids.variant2, ids.formerVariant]);
await db.query("insert into enrollments(tenant_id,profile_id,course_id) values($1,$2,$4),($1,$3,$4)", [ids.tenant, ids.student1, ids.student2, ids.course]);

const value = async (functionName, parameters) => (
  await db.query(`select public.${functionName}(${parameters.map((_, index) => `$${index + 1}::uuid`).join(",")}) as value`, parameters)
).rows[0].value;

const overview = await value("teacher_class_overview_metrics", [ids.tenant, ids.teacher]);
assert.equal(overview.class_accuracy, 90);
assert.equal(overview.students, 2);
assert.equal(overview.total_attempts, 3);
assert.deepEqual(overview.content, { documents: 1, quiz_sets: 2, published: 1, drafts: 1 });
assert.deepEqual(overview.pipeline, { pending_review: 1, approved: 1, rejected: 0, needs_edit: 0 });
assert.deepEqual(overview.accuracy_by_quiz.map(row => [row.title, row.accuracy, row.attempts]), [
  ["Published", 85, 2], ["Draft", 95, 1],
]);
assert.deepEqual(overview.score_distribution.map(row => row.count), [0, 0, 1, 2]);

const subjects = await value("teacher_subject_metrics", [ids.tenant, ids.teacher]);
assert.equal(subjects.length, 1);
assert.deepEqual(subjects[0], {
  id: ids.subject,
  name: "Accounting",
  course_name: "CA",
  level_name: "Foundation",
  chapters: 1,
  quizzes_total: 2,
  quizzes_published: 1,
  quizzes_draft: 1,
  questions: 2,
  pending_review: 1,
  needs_edit: 0,
  attempts: 3,
  students: 2,
  avg_score_pct: 90,
  score_earned: 36,
  score_possible: 40,
});

const chapters = await value("teacher_chapter_metrics", [ids.tenant, ids.teacher, ids.subject]);
assert.deepEqual(chapters, [{
  id: ids.chapter,
  name: "Basics",
  order_index: 1,
  quiz_count: 2,
  question_count: 3,
}]);

const published = await value("teacher_published_quiz_metrics", [ids.tenant, ids.teacher]);
assert.equal(published.quizzes.length, 1);
assert.deepEqual(
  Object.fromEntries(Object.entries(published.quizzes[0]).filter(([key]) => !["published_at", "last_activity"].includes(key))),
  {
    id: ids.quiz1,
    title: "Published",
    subject: "Accounting",
    eligible_students: 2,
    completed_students: 2,
    not_started_students: 0,
    total_attempts: 2,
    average_accuracy: 85,
    highest_accuracy: 100,
    lowest_accuracy: 70,
  },
);

assert.deepEqual(await value("teacher_subject_metrics", [ids.tenant, ids.otherTeacher]), []);
assert.deepEqual(await value("teacher_chapter_metrics", [ids.tenant, ids.teacher, ids.formerSubject]), []);
assert.deepEqual((await value("teacher_published_quiz_metrics", [ids.tenant, ids.otherTeacher])).quizzes, []);

for (const signature of [
  "public.teacher_class_overview_metrics(uuid,uuid)",
  "public.teacher_subject_metrics(uuid,uuid)",
  "public.teacher_chapter_metrics(uuid,uuid,uuid)",
  "public.teacher_published_quiz_metrics(uuid,uuid)",
]) {
  assert.equal((await db.query("select has_function_privilege('anon', $1, 'EXECUTE') as allowed", [signature])).rows[0].allowed, false);
  assert.equal((await db.query("select has_function_privilege('authenticated', $1, 'EXECUTE') as allowed", [signature])).rows[0].allowed, false);
  assert.equal((await db.query("select has_function_privilege('service_role', $1, 'EXECUTE') as allowed", [signature])).rows[0].allowed, true);
}

for (const indexName of [
  "idx_teacher_subjects_tenant_teacher_subject",
  "idx_chapters_tenant_subject",
  "idx_documents_tenant_uploader_created",
  "idx_questions_tenant_creator_chapter",
  "idx_quizsets_tenant_creator_status",
  "idx_variants_tenant_quizset",
  "idx_vq_tenant_variant",
  "idx_attempts_tenant_variant_status",
  "idx_enrollments_tenant_course_profile",
]) {
  assert.equal(
    (await db.query("select count(*)::int as count from pg_indexes where indexname = $1", [indexName])).rows[0].count,
    1,
    `${indexName} must exist for the aggregate access paths`,
  );
}

await db.exec(`
  set arivupro.explain_tenant = '${ids.tenant}';
  set arivupro.explain_teacher = '${ids.teacher}';
  set arivupro.explain_subject = '${ids.subject}';
`);
await db.exec(explainScript);

await db.close();
console.log("teacher dashboard aggregate migration checks passed");
