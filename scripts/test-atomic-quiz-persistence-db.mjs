// Isolated PostgreSQL atomicity/security checks for migration 72.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration = fs.readFileSync(
  "migrations/migration-72-atomic-quiz-persistence.sql",
  "utf8",
);

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create type public.user_role as enum ('super_admin','institution_admin','teacher','student');
  create type public.question_type as enum (
    'mcq_single','mcq_multi','numerical','true_false','fill_blank',
    'descriptive','assertion_reason','mrm','matching'
  );
  create type public.question_source as enum ('ai_generated','manual','extracted');
  create type public.review_status as enum ('pending_review','approved','rejected','needs_edit');
  create type public.document_status as enum ('uploaded','processing','completed','failed','archived');
  create type public.job_status as enum ('queued','running','succeeded','failed');
  create type public.variant_type as enum ('theory','practical','mixed');
  create type public.quiz_status as enum ('draft','published','archived');

  create table public.tenants (
    id uuid primary key, is_active boolean not null default true
  );
  create table public.profiles (
    id uuid primary key, tenant_id uuid not null, role public.user_role not null
  );
  create table public.subjects (
    id uuid primary key, tenant_id uuid not null, name text not null
  );
  create table public.teacher_subjects (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    teacher_id uuid not null, subject_id uuid not null
  );
  create table public.chapters (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    subject_id uuid not null, name text not null,
    unique(tenant_id, subject_id, name)
  );
  create table public.topics (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    chapter_id uuid not null, name text not null
  );
  create table public.documents (
    id uuid primary key, tenant_id uuid not null, uploaded_by uuid,
    chapter_id uuid, status public.document_status not null default 'uploaded'
  );
  create table public.ai_extraction_jobs (
    id uuid primary key, tenant_id uuid not null, document_id uuid not null,
    status public.job_status not null default 'running', model_used text,
    raw_output jsonb, overall_confidence numeric, error_message text,
    completed_at timestamptz
  );
  create table public.questions (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    created_by uuid, chapter_id uuid, topic_id uuid, extraction_job_id uuid,
    type public.question_type not null, question_text text not null,
    options jsonb, correct_answer jsonb not null, explanation text,
    difficulty text, marks numeric not null default 1,
    source public.question_source not null, review_status public.review_status not null,
    source_excerpt text, source_page_start integer, source_page_end integer,
    grounding_confidence numeric, verification_status text,
    verification_warnings jsonb, confidence_score numeric,
    paper_type text, paper_year text, paper_exam text, paper_source_note text,
    model_answer text, answer_summary text
  );
  create table public.quiz_sets (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    created_by uuid, document_id uuid, subject_id uuid, chapter_id uuid,
    title text not null, status public.quiz_status not null
  );
  create table public.quiz_variants (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    quiz_set_id uuid not null references public.quiz_sets(id) on delete cascade,
    variant_type public.variant_type not null, total_marks numeric
  );
  create table public.quiz_variant_questions (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    variant_id uuid not null references public.quiz_variants(id) on delete cascade,
    question_id uuid not null references public.questions(id), order_index integer
  );
`);

await db.exec(migration);
await db.exec(migration);

const id = (suffix) => `00000000-0000-4000-8000-${suffix.padStart(12, "0")}`;
const ids = {
  tenant: id("1"), otherTenant: id("2"), actor: id("10"), otherActor: id("11"),
  subject: id("20"), chapter: id("30"), document: id("40"), extraction: id("50"),
  failedExtraction: id("51"),
};
await db.query("insert into tenants(id) values($1),($2)", [ids.tenant, ids.otherTenant]);
await db.query(
  "insert into profiles(id,tenant_id,role) values($1,$2,'teacher'),($3,$4,'teacher')",
  [ids.actor, ids.tenant, ids.otherActor, ids.otherTenant],
);
await db.query("insert into subjects(id,tenant_id,name) values($1,$2,'Accounts')", [ids.subject, ids.tenant]);
await db.query(
  "insert into teacher_subjects(tenant_id,teacher_id,subject_id) values($1,$2,$3)",
  [ids.tenant, ids.actor, ids.subject],
);
await db.query(
  "insert into chapters(id,tenant_id,subject_id,name) values($1,$2,$3,'Basics')",
  [ids.chapter, ids.tenant, ids.subject],
);
await db.query(
  "insert into documents(id,tenant_id,uploaded_by,status) values($1,$2,$3,'uploaded')",
  [ids.document, ids.tenant, ids.actor],
);

const generated = {
  document_id: ids.document,
  subject_id: ids.subject,
  chapter_name: "Atomic chapter",
  selected_topics: ["Equity"],
  title: "Atomic quiz",
  variant_type: "mixed",
  source: "ai_generated",
  provider: "fixture",
  blueprint: { total: 2 },
  questions: [
    {
      topic: "Equity", type: "mcq_single", question_text: "What is equity?",
      options: [{ id: "A", text: "60" }, { id: "B", text: "140" }],
      correct_answer: "A", difficulty: "easy", marks: 1,
      verification_status: "verified", verification_warnings: [],
    },
    {
      type: "numerical", question_text: "Calculate equity.", options: null,
      correct_answer: { value: 60, tolerance: 0 }, difficulty: "easy", marks: 2,
      verification_status: "verified", verification_warnings: [],
    },
  ],
};
const persist = async (payload, tenant = ids.tenant, actor = ids.actor) => (
  await db.query(
    "select public.persist_generated_quiz($1::uuid,$2::uuid,$3::jsonb) as value",
    [tenant, actor, payload],
  )
).rows[0].value;

const result = await persist(generated);
assert.ok(result.quiz_set_id);
assert.equal(result.questions.length, 2);
assert.equal(result.questions.every((question) => question.review_status === "pending_review"), true);
assert.equal(Number((await db.query("select total_marks from quiz_variants")).rows[0].total_marks), 3);
assert.equal((await db.query("select count(*)::int as count from quiz_variant_questions")).rows[0].count, 2);
assert.equal((await db.query("select count(*)::int as count from topics where name='Equity'")).rows[0].count, 1);
assert.equal((await db.query("select count(*)::int as count from questions where topic_id is not null")).rows[0].count, 1);

const beforeFailure = {
  quizzes: (await db.query("select count(*)::int as count from quiz_sets")).rows[0].count,
  questions: (await db.query("select count(*)::int as count from questions")).rows[0].count,
  links: (await db.query("select count(*)::int as count from quiz_variant_questions")).rows[0].count,
};
await assert.rejects(persist({
  ...generated,
  title: "Must roll back",
  questions: [...generated.questions, { ...generated.questions[0], type: "invalid" }],
}));
assert.deepEqual({
  quizzes: (await db.query("select count(*)::int as count from quiz_sets")).rows[0].count,
  questions: (await db.query("select count(*)::int as count from questions")).rows[0].count,
  links: (await db.query("select count(*)::int as count from quiz_variant_questions")).rows[0].count,
}, beforeFailure);
await assert.rejects(persist(generated, ids.otherTenant, ids.otherActor));

await db.query(
  "insert into ai_extraction_jobs(id,tenant_id,document_id,status) values($1,$2,$3,'running')",
  [ids.failedExtraction, ids.tenant, ids.document],
);
await assert.rejects(persist({
  ...generated,
  chapter_name: undefined,
  chapter_id: ids.chapter,
  selected_topics: undefined,
  extraction_job_id: ids.failedExtraction,
  title: "Failed import must roll back",
  source: "extracted",
  questions: [...generated.questions, { ...generated.questions[0], type: "invalid" }],
}));
assert.deepEqual({
  quizzes: (await db.query("select count(*)::int as count from quiz_sets")).rows[0].count,
  questions: (await db.query("select count(*)::int as count from questions")).rows[0].count,
  links: (await db.query("select count(*)::int as count from quiz_variant_questions")).rows[0].count,
}, beforeFailure);
assert.equal((await db.query(
  "select status from ai_extraction_jobs where id=$1",
  [ids.failedExtraction],
)).rows[0].status, "running");

await db.query(
  "insert into ai_extraction_jobs(id,tenant_id,document_id,status) values($1,$2,$3,'running')",
  [ids.extraction, ids.tenant, ids.document],
);
const imported = await persist({
  ...generated,
  chapter_name: undefined,
  chapter_id: ids.chapter,
  selected_topics: undefined,
  extraction_job_id: ids.extraction,
  title: "Imported paper",
  source: "extracted",
  import_summary: { candidates: 1, imported: 1, skipped: 0 },
  extraction_raw_output: { import_summary: { candidates: 1, imported: 1, skipped: 0 } },
  overall_confidence: 0.9,
  questions: [{
    ...generated.questions[0], paper_type: "pyq", paper_year: "2025",
    paper_exam: "Foundation", model_answer: "Sixty", answer_summary: "60",
    confidence: 0.9,
  }],
});
assert.equal(imported.extraction_job_id, ids.extraction);
const extraction = (await db.query(
  "select status,model_used,raw_output,overall_confidence from ai_extraction_jobs where id=$1",
  [ids.extraction],
)).rows[0];
assert.equal(extraction.status, "succeeded");
assert.equal(extraction.model_used, "fixture");
assert.equal(Number(extraction.overall_confidence), 0.9);
const paper = (await db.query(
  "select review_status,paper_type,paper_year,paper_exam,model_answer,answer_summary from questions where extraction_job_id=$1",
  [ids.extraction],
)).rows[0];
assert.deepEqual(paper, {
  review_status: "pending_review", paper_type: "pyq", paper_year: "2025",
  paper_exam: "Foundation", model_answer: "Sixty", answer_summary: "60",
});

await db.exec("set role authenticated");
await assert.rejects(db.query(
  "select public.persist_generated_quiz($1::uuid,$2::uuid,$3::jsonb)",
  [ids.tenant, ids.actor, generated],
));
await db.exec("reset role");

console.log("migration 72 atomic quiz persistence checks passed");
await db.close();
