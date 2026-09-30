// Isolated evaluation schema and lease tests. No hosted database access.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const scalar = async (sql, params = []) => Object.values((await db.query(sql, params)).rows[0])[0];
const uuid = () => crypto.randomUUID();

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create schema auth;
  create schema storage;
  create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
  create function public.current_tenant_id() returns uuid language sql stable as $$ select null::uuid $$;
  create function public.is_staff() returns boolean language sql stable as $$ select false $$;
  create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
  create table public.tenants(id uuid primary key,name text,subdomain text,is_active boolean default true,handwritten_evaluation_enabled boolean default false);
  create table public.profiles(id uuid primary key,tenant_id uuid references tenants(id),role text,unique(id,tenant_id));
  create table public.courses(id uuid primary key,tenant_id uuid references tenants(id),name text,unique(id,tenant_id));
  create table public.course_levels(id uuid primary key,tenant_id uuid references tenants(id),course_id uuid,name text,unique(id,tenant_id));
  create table public.subjects(id uuid primary key,tenant_id uuid references tenants(id),course_id uuid,course_level_id uuid,name text,unique(id,tenant_id,course_level_id));
  create table public.enrollments(id uuid primary key default gen_random_uuid(),tenant_id uuid,profile_id uuid,course_id uuid,course_level_id uuid);
  create table public.generated_papers(id uuid primary key,tenant_id uuid references tenants(id));
  create table public.ai_rate_limits(
    tenant_id uuid not null,user_id uuid not null,endpoint text not null,
    window_started_at timestamptz not null,request_count integer not null,updated_at timestamptz not null,
    primary key(tenant_id,user_id,endpoint)
  );
  create table public.api_call_logs(
    id uuid primary key default gen_random_uuid(),
    job_id uuid,
    created_at timestamptz not null default now()
  );
`);
await db.exec("create unique index uq_subjects_id_tenant on subjects(id,tenant_id)");

const migration = fs.readFileSync("migrations/migration-78-handwritten-evaluation-phase-a.sql", "utf8");
await db.exec(migration);
await db.exec(migration);
const stage1Migration = fs.readFileSync("migrations/migration-79-handwritten-stage1.sql", "utf8");
await db.exec(stage1Migration);
await db.exec(stage1Migration);
const rubricMigration = fs.readFileSync("migrations/migration-80-handwritten-rubric.sql", "utf8");
await db.exec(rubricMigration);
await db.exec(rubricMigration);
const stage2Migration = fs.readFileSync("migrations/migration-81-handwritten-stage2.sql", "utf8");
await db.exec(stage2Migration);
await db.exec(stage2Migration);
const learningMigration = fs.readFileSync("migrations/migration-82-handwritten-learning.sql", "utf8");
await db.exec(learningMigration);
await db.exec(learningMigration);
const telemetryMigration = fs.readFileSync("migrations/migration-83-evaluation-ai-telemetry.sql", "utf8");
await db.exec(telemetryMigration);
await db.exec(telemetryMigration);

const tenantA = uuid(), tenantB = uuid(), teacherA = uuid(), studentA = uuid(), otherA = uuid();
const courseA = uuid(), levelA = uuid(), subjectA = uuid(), generated = uuid(), paper = uuid(), intent = uuid();
await db.query("insert into tenants(id,name,subdomain,is_active,handwritten_evaluation_enabled) values($1,'A','a',true,true),($2,'B','b',true,true)", [tenantA, tenantB]);
await db.query("insert into profiles(id,tenant_id,role) values($1,$2,'teacher'),($3,$2,'student'),($4,$2,'student')", [teacherA, tenantA, studentA, otherA]);
await db.query("insert into courses(id,tenant_id,name) values($1,$2,'Commerce')", [courseA, tenantA]);
await db.query("insert into course_levels(id,tenant_id,course_id,name) values($1,$2,$3,'Foundation')", [levelA, tenantA, courseA]);
await db.query("insert into subjects(id,tenant_id,course_id,course_level_id,name) values($1,$2,$3,$4,'Accounts')", [subjectA, tenantA, courseA, levelA]);
await db.query("insert into enrollments(tenant_id,profile_id,course_id,course_level_id) values($1,$2,$3,$4)", [tenantA, studentA, courseA, levelA]);
await db.query("insert into generated_papers(id,tenant_id) values($1,$2)", [generated, tenantA]);
await db.query(`insert into evaluation_papers(id,tenant_id,course_level_id,subject_id,title,question_paper_storage_path,total_marks,generated_paper_id,created_by)
  values($1,$2,$3,$4,'Mock','paper.pdf',100,$5,$6)`, [paper, tenantA, levelA, subjectA, generated, teacherA]);

const rubricJob = await scalar("select to_jsonb(j) from evaluation_jobs j where evaluation_paper_id=$1", [paper]);
assert.equal(rubricJob.kind, "build_rubric", "paper creation automatically enqueues its frozen rubric");
await assert.rejects(db.query(
  "insert into evaluation_jobs(tenant_id,evaluation_paper_id,owner_teacher_id,kind) values($1,$2,$3,'build_rubric')",
  [tenantA, paper, teacherA],
), undefined, "the durable per-paper lock prevents a concurrent duplicate rubric build");
const rubricWorker = uuid(), competingWorker = uuid();
const claimedRubric = await scalar("select claim_evaluation_job($1)", [rubricWorker]);
assert.equal(claimedRubric.id, rubricJob.id);
assert.equal(await scalar("select claim_evaluation_job($1)", [competingWorker]), null,
  "only one worker can hold the rubric lease");
assert.equal(await scalar("select start_evaluation_job($1,$2)", [rubricJob.id, rubricWorker]), true);
assert.equal(await scalar("select rubric_status from evaluation_papers where id=$1", [paper]), "extracting");
assert.equal(await scalar("select checkpoint_evaluation_rubric_texts($1,$2,$3,$4)",
  [rubricJob.id, rubricWorker, "Q1 Question (100 marks)", "Official answer"]), true);
assert.equal(await scalar("select rubric_status from evaluation_papers where id=$1", [paper]), "generating");
const frozen = [{question_ref: "Q1", question_text: "Q1 Question (100 marks)", marks: 100}];
const structure = {compulsory: ["Q1"], optional_groups: [], backend_validated: true};
assert.equal(await scalar("select finish_evaluation_rubric_job($1,$2,$3::jsonb,$4::jsonb,$5)",
  [rubricJob.id, rubricWorker, JSON.stringify(frozen), JSON.stringify(structure), "official"]), true);
assert.equal(await scalar("select rubric_status from evaluation_papers where id=$1", [paper]), "ready");
assert.deepEqual(await scalar("select structured_qa from evaluation_papers where id=$1", [paper]), frozen);

await db.query(`insert into evaluation_upload_intents(id,tenant_id,student_id,evaluation_paper_id,storage_path,original_filename,content_type,expected_size,status,verified_at)
  values($1,$2,$3,$4,'answer.pdf','answer.pdf','application/pdf',5,'verified',now())`, [intent, tenantA, studentA, paper]);

const createSubmission = () => scalar(
  "select create_handwritten_submission_job($1,$2,$3)", [tenantA, studentA, intent]
);
const first = await createSubmission();
const replay = await createSubmission();
assert.equal(replay.submission.id, first.submission.id, "intent replay returns the same submission");
assert.equal(replay.job.id, first.job.id, "intent replay returns the same job");
await db.query("insert into api_call_logs(evaluation_job_id) values($1)", [first.job.id]);
assert.equal(await scalar("select evaluation_job_id from api_call_logs limit 1"), first.job.id);
await assert.rejects(db.query("insert into api_call_logs(evaluation_job_id) values($1)", [uuid()]),
  undefined, "evaluation telemetry rejects an unknown evaluation job");
assert.equal(await scalar("select count(*)::int from handwritten_submissions"), 1);
assert.equal(await scalar("select count(*)::int from evaluation_jobs"), 2);

await assert.rejects(db.query(
  "insert into evaluation_jobs(tenant_id,submission_id,owner_student_id) values($1,$2,$3)",
  [tenantA, first.submission.id, otherA],
), undefined, "owner mismatch must fail closed at the tenant-safe FK");
await assert.rejects(db.query(
  "insert into evaluation_papers(tenant_id,course_level_id,subject_id,title,question_paper_storage_path,total_marks,created_by) values($1,$2,$3,'Cross tenant','cross.pdf',10,$4)",
  [tenantB, levelA, subjectA, teacherA],
), undefined, "cross-tenant academic references must be rejected");

const workerOne = uuid(), workerTwo = uuid();
const claimed = await scalar("select claim_evaluation_job($1)", [workerOne]);
assert.equal(claimed.id, first.job.id);
assert.equal(await scalar("select claim_evaluation_job($1)", [workerTwo]), null, "a live lease cannot be double-claimed");
assert.equal(await scalar("select start_evaluation_job($1,$2)", [claimed.id, workerTwo]), false, "another worker cannot start the lease");
await db.query("update evaluation_jobs set lease_expires_at=now()-interval '1 second' where id=$1", [claimed.id]);
const reclaimed = await scalar("select claim_evaluation_job($1)", [workerTwo]);
assert.equal(reclaimed.id, claimed.id);
assert.equal(reclaimed.attempts, 2);
assert.equal(await scalar("select start_evaluation_job($1,$2)", [reclaimed.id, workerTwo]), true);
assert.equal(await scalar("select status from handwritten_submissions where id=$1", [first.submission.id]), "processing_stage1");
assert.equal(await scalar("select heartbeat_evaluation_job($1,$2)", [reclaimed.id, workerTwo]), true);
const extraction = {text_answers: [], tables: [], numerical_workings: [], page_manifest: [], legibility_report: {overall_legibility: "clear"}};
assert.equal(await scalar("select finish_evaluation_stage1_job($1,$2,$3::jsonb,$4,$5::jsonb,false)",
  [reclaimed.id, workerTwo, JSON.stringify(extraction), "answer.pdf", JSON.stringify({})]), true);
assert.equal(await scalar("select status from handwritten_submissions where id=$1", [first.submission.id]), "stage1_complete");
assert.deepEqual(await scalar("select stage1_extraction from handwritten_submissions where id=$1", [first.submission.id]), extraction);
assert.equal(await scalar("select status from evaluation_jobs where id=$1", [first.job.id]), "processing");
assert.equal(await scalar("select begin_evaluation_stage2($1,$2)", [reclaimed.id, workerTwo]), true);
assert.equal(await scalar("select status from handwritten_submissions where id=$1", [first.submission.id]), "processing_stage2");
const evaluation = uuid();
const summary = {total_marks_obtained: 60, total_marks_possible: 100, percentage: 60,
  overall_feedback: "Complete", strengths: ["Q1"], areas_to_improve: []};
const questions = [{question_ref: "Q1", question_text: "Question", marks_obtained: 60,
  marks_possible: 100, not_attempted: false, not_evaluated: false, not_counted: false,
  mapping_status: "matched", feedback: "", student_guidance: {}, student_answer_excerpt: "answer",
  handwriting_legibility: "clear", grading_confidence: 1, criteria_breakdown: []}];
const content = '{"results":[]}';
const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(content));
const sha = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
const artifacts = [{sequence: 1, route: "whole_paper", model: "deepseek", prompt_revision: "v2.3-text-json",
  raw_content: content, content_bytes: content.length, content_sha256: sha, content_omitted: false}];
assert.equal(await scalar("select finish_evaluation_stage2_job($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,false)",
  [reclaimed.id, workerTwo, evaluation, JSON.stringify(summary), JSON.stringify(questions), JSON.stringify(artifacts)]), true);
assert.equal(await scalar("select status from handwritten_submissions where id=$1", [first.submission.id]), "evaluated");
assert.equal(await scalar("select status from evaluation_jobs where id=$1", [first.job.id]), "done");
assert.equal(await scalar("select tenant_id from handwritten_evaluations where id=$1", [evaluation]), tenantA);
assert.equal(await scalar("select count(*)::int from handwritten_question_evaluations where evaluation_id=$1", [evaluation]), 1);
assert.equal(await scalar("select count(*)::int from handwritten_stage2_artifacts where evaluation_id=$1", [evaluation]), 1);
const questionResult = await scalar("select id from handwritten_question_evaluations where evaluation_id=$1", [evaluation]);
const mistakeRows = [{question_result_id: questionResult, category: "conceptual", severity: "major",
  description: "Missing treatment", marks_lost: 4, suggestion: "Apply the treatment",
  chapter_name: "Accounting Standards", criterion_key: "correct treatment",
  signature: "a".repeat(64)}];
assert.equal(await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluation, JSON.stringify(mistakeRows)]), 1);
assert.equal(await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluation, JSON.stringify(mistakeRows)]), 1, "mistake rebuild is idempotent");
assert.equal(await scalar("select count(*)::int from handwritten_mistakes where evaluation_id=$1", [evaluation]), 1);
assert.equal(await scalar("select reconcile_handwritten_revision_items($1,$2,$3)",
  [tenantA, studentA, subjectA]), true);
assert.equal(await scalar("select priority from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), "high");
assert.equal(Number(await scalar("select marks_at_risk from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA])), 4);
const lowMistake = [{...mistakeRows[0], marks_lost: 0.5, severity: "minor"}];
assert.equal(await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluation, JSON.stringify(lowMistake)]), 1);
await scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]);
assert.equal(await scalar("select priority from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), "low");
const mediumMistake = [{...mistakeRows[0], marks_lost: 1.5, severity: "moderate"}];
await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluation, JSON.stringify(mediumMistake)]);
await scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]);
assert.equal(await scalar("select priority from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), "medium");
await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluation, JSON.stringify(mistakeRows)]);
await scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]);
await Promise.all([
  scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]),
  scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]),
]);
assert.equal(await scalar("select count(*)::int from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), 1, "concurrent reconciliation keeps one topic row");

const paperTwo = uuid(), intentTwo = uuid(), submissionTwo = uuid(), evaluationTwo = uuid();
await db.query(`insert into evaluation_papers(id,tenant_id,course_level_id,subject_id,title,question_paper_storage_path,total_marks,generated_paper_id,created_by)
  values($1,$2,$3,$4,'Mock 2','paper-2.pdf',100,$5,$6)`, [paperTwo, tenantA, levelA, subjectA, generated, teacherA]);
await db.query(`insert into evaluation_upload_intents(id,tenant_id,student_id,evaluation_paper_id,storage_path,original_filename,content_type,expected_size,status,verified_at)
  values($1,$2,$3,$4,'answer-2.pdf','answer-2.pdf','application/pdf',5,'verified',now())`, [intentTwo, tenantA, studentA, paperTwo]);
await db.query(`insert into handwritten_submissions(id,tenant_id,student_id,evaluation_paper_id,upload_intent_id,answer_script_path,status)
  values($1,$2,$3,$4,$5,'answer-2.pdf','evaluated')`, [submissionTwo, tenantA, studentA, paperTwo, intentTwo]);
await db.query(`insert into handwritten_evaluations(id,tenant_id,submission_id,total_marks_obtained,total_marks_possible,percentage)
  values($1,$2,$3,60,100,60)`, [evaluationTwo, tenantA, submissionTwo]);
const questionResultTwo = uuid();
await db.query(`insert into handwritten_question_evaluations(id,tenant_id,evaluation_id,question_ref,marks_obtained,marks_possible,mapping_status)
  values($1,$2,$3,'Q1',96,100,'matched')`, [questionResultTwo, tenantA, evaluationTwo]);
const recurringMistake = [{...mistakeRows[0], question_result_id: questionResultTwo}];
await scalar("select replace_handwritten_mistakes($1,$2,$3::jsonb)",
  [tenantA, evaluationTwo, JSON.stringify(recurringMistake)]);
await scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]);
assert.equal(await scalar("select count(*)::int from handwritten_mistakes where signature=$1 and is_recurring",
  [mistakeRows[0].signature]), 2, "the same signature recurs only across distinct current papers");
assert.equal(await scalar("select source_count from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), 2);
assert.equal(await scalar("select replace_handwritten_mistakes($1,$2,'[]'::jsonb)", [tenantA, evaluation]), 0);
assert.equal(await scalar("select replace_handwritten_mistakes($1,$2,'[]'::jsonb)", [tenantA, evaluationTwo]), 0);
assert.equal(await scalar("select reconcile_handwritten_revision_items($1,$2,$3)", [tenantA, studentA, subjectA]), true);
assert.equal(await scalar("select is_resolved from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), true, "topics absent from current mistakes auto-resolve");
assert.equal(await scalar("select resolution_source from handwritten_revision_items where student_id=$1 and subject_id=$2",
  [studentA, subjectA]), "improved");
await db.query(`insert into handwritten_student_analytics(
  tenant_id,student_id,subject_id,total_attempts,avg_percentage,best_percentage,
  latest_percentage,score_history,current_level,improvement_rate
 ) values($1,$2,$3,1,60,60,60,'[]','proficient',0)`, [tenantA, studentA, subjectA]);
assert.equal(await scalar(`select count(*)::int from information_schema.columns
  where table_name='handwritten_student_analytics'
   and column_name in('weak_chapters','top_mistake_categories','presentation_scores','streak_count')`), 0,
  "Option A analytics intentionally omits ExamApp's unused fields");

const holderOne = uuid(), holderTwo = uuid();
assert.equal(await scalar("select acquire_ai_provider_slot('deepseek',$1,1,900)", [holderOne]), true);
assert.equal(await scalar("select acquire_ai_provider_slot('deepseek',$1,1,900)", [holderTwo]), false);
assert.equal(await scalar("select release_ai_provider_slot('deepseek',$1)", [holderOne]), true);
assert.equal(await scalar("select acquire_ai_provider_slot('deepseek',$1,1,900)", [holderTwo]), true);
const limited = await db.query("select * from consume_ai_rate_limit($1,$2,'handwritten_evaluation',1)", [tenantA, studentA]);
assert.equal(limited.rows[0].allowed, true);
const blocked = await db.query("select * from consume_ai_rate_limit($1,$2,'handwritten_evaluation',1)", [tenantA, studentA]);
assert.equal(blocked.rows[0].allowed, false);

await db.exec("set role authenticated");
await assert.rejects(db.query("select * from evaluation_jobs"));
await assert.rejects(db.query("select claim_evaluation_job(gen_random_uuid())"));
await assert.rejects(db.query("select * from handwritten_mistakes"));
await assert.rejects(db.query("select * from handwritten_revision_items"));
await assert.rejects(db.query("select * from handwritten_student_analytics"));
await db.exec("reset role");

console.log("PASS: evaluation Stage 1-2 learning lifecycle, tenant FKs, atomic persistence, reconciliation, provider slots and rate limits");
await db.close();
