// Isolated Postgres integration tests. No connection string or hosted DB access.
// Install @electric-sql/pglite@0.3.14 under .tmp/pg-test, then run with Node.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

process.on("uncaughtException", () => { console.error("Database migration test failed."); process.exit(1); });

const db = new PGlite();
const schema = fs.readFileSync("migrations/schema.sql", "utf8");
await db.exec("create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create table auth.users(id uuid primary key);");
for (const type of schema.matchAll(/^create type .*?;$/gm)) await db.exec(type[0]);
await db.exec("alter type question_source add value 'extracted';");
for (const name of ["tenants", "profiles", "catalog_courses", "catalog_course_levels", "catalog_course_subjects", "courses", "course_levels", "subjects", "teacher_subjects", "chapters", "topics", "documents", "ai_extraction_jobs", "questions", "quiz_sets", "quiz_variants", "quiz_variant_questions", "quiz_generation_jobs", "quiz_attempts"]) {
  const definition = schema.match(new RegExp(`create table ${name} \\([\\s\\S]*?\\n\\);`));
  assert.ok(definition, name);
  await db.exec(definition[0].replace(/^.*embedding vector.*\r?\n/m, ""));
  if (name === "profiles" || name === "subjects") {
    await db.exec(`create unique index on ${name}(id,tenant_id)`);
  }
}
const eventSchema=fs.readFileSync("migrations/migration-02-events.sql","utf8");
await db.exec(eventSchema.match(/create table if not exists events \([\s\S]*?\n\);/)[0]);
// The existing quota function is independently tested by the backend suite.
// This fixture makes quota consumption observable across transaction retries.
await db.exec(`create table quota_calls(n int); insert into quota_calls values(0);
  create function public.consume_ai_rate_limit(uuid,uuid,text,int)
  returns table(allowed boolean,retry_after_seconds int,remaining int) language plpgsql as $$
  begin update public.quota_calls set n=n+1; return query select true,0,10; end $$;`);
const facultyMigration = fs.readFileSync("migrations/migration-43-faculty-background-jobs.sql", "utf8");
await db.exec(facultyMigration);
await db.exec(facultyMigration); // Safe when the earlier Pavya SQL was already applied.
const scalar = async (sql, params=[]) => Object.values((await db.query(sql, params)).rows[0])[0];
const uuid = () => crypto.randomUUID();
const tenant=uuid(), actor=uuid(), subject=uuid(), course=uuid(), level=uuid(), doc=uuid(), chapter=uuid();
await db.query("insert into tenants(id,name,subdomain) values($1,'Pilot','pilot')",[tenant]);
await db.query("insert into auth.users values($1)",[actor]);
await db.query("insert into profiles(id,tenant_id,role) values($1,$2,'teacher')",[actor,tenant]);
await db.query("insert into courses(id,tenant_id,name) values($1,$2,'Commerce')",[course,tenant]);
await db.query("insert into course_levels(id,tenant_id,course_id,name) values($1,$2,$3,'Foundation')",[level,tenant,course]);
await db.query("insert into subjects(id,tenant_id,course_id,course_level_id,name) values($1,$2,$3,$4,'Accounts')",[subject,tenant,course,level]);
await db.query("insert into teacher_subjects(tenant_id,teacher_id,subject_id) values($1,$2,$3)",[tenant,actor,subject]);
await db.query("insert into chapters(id,tenant_id,subject_id,name) values($1,$2,$3,'Basics')",[chapter,tenant,subject]);
await db.query("insert into documents(id,tenant_id,uploaded_by,storage_path) values($1,$2,$3,'test.docx')",[doc,tenant,actor]);
// Match the existing figure-link shape without invoking storage or extraction.
await db.exec('alter table questions add column figure_id uuid;');
const source=uuid(), variant=uuid(), question=uuid(), figure=uuid();
await db.query("insert into quiz_sets(id,tenant_id,subject_id,chapter_id,document_id,title,status,created_by) values($1,$2,$3,$4,$5,'Original','published',$6)", [source,tenant,subject,chapter,doc,actor]);
await db.query("insert into quiz_variants(id,tenant_id,quiz_set_id,variant_type,total_marks) values($1,$2,$3,'mixed',2)",[variant,tenant,source]);
await db.query(`insert into questions(id,tenant_id,chapter_id,type,question_text,options,correct_answer,review_status,created_by,figure_id,marks)
 values($1,$2,$3,'mcq_single','What is equity?', '[{"id":"A","text":"Assets less liabilities"},{"id":"B","text":"Liabilities"}]','"A"','approved',$4,$5,1)`,[question,tenant,chapter,actor,figure]);
await db.query("insert into quiz_variant_questions(tenant_id,variant_id,question_id,marks_override) values($1,$2,$3,2)",[tenant,variant,question]);
const originalBefore=await scalar('select to_jsonb(q) from questions q where id=$1',[question]);
const student=uuid(), attempt=uuid();
await db.query('insert into auth.users values($1)',[student]);
await db.query("insert into profiles(id,tenant_id,role) values($1,$2,'student')",[student,tenant]);
await db.query('insert into quiz_attempts(id,tenant_id,variant_id,student_id,question_snapshot,total_score) values($1,$2,$3,$4,$5,2)',[attempt,tenant,variant,student,[originalBefore]]);
const historicalAttempt=await scalar('select to_jsonb(a) from quiz_attempts a where id=$1',[attempt]);
const migration=fs.readFileSync('migrations/migration-51-safe-quiz-reuse.sql','utf8');
await db.exec(migration);
await db.exec(migration);
assert.equal(await scalar('select release_locked from questions where id=$1',[question]),false,
  'migration rollout must not retroactively lock existing quizzes while the feature flag is off');
const state=id=>scalar('select quiz_publication_state($1,$2,$3)',[id,tenant,actor]);
const copy=(id,key=uuid(),title='Copy')=>scalar('select copy_quiz_draft($1,$2,$3,$4,$5)',[id,tenant,actor,key,title]);
const publish=(id,token)=>scalar('select publish_quiz_atomic($1,$2,$3,$4)',[id,tenant,actor,token]);
const key=uuid(), copied=await copy(source,key);
assert.equal((await copy(source,key)).quiz_set_id,copied.quiz_set_id);
await assert.rejects(copy(source,key,'Different title'));
const copyId=copied.quiz_set_id;
const copiedRow=await scalar('select to_jsonb(q) from questions q join quiz_variant_questions l on l.question_id=q.id join quiz_variants v on v.id=l.variant_id where v.quiz_set_id=$1',[copyId]);
assert.notEqual(copiedRow.id,question);
assert.equal(copiedRow.figure_id,figure);
assert.equal(copiedRow.origin_question_id,question);
assert.equal(copiedRow.source_quiz_id,source);
assert.equal(copiedRow.release_locked,false);
assert.equal(copiedRow.correct_answer,originalBefore.correct_answer);
assert.equal(await scalar('select status from quiz_sets where id=$1',[copyId]),'draft');
assert.equal(await scalar('select count(*)::int from quiz_attempts'),1);
const stale=(await state(copyId)).publication_token;
await db.query("update questions set question_text='Updated copy' where id=$1",[copiedRow.id]);
assert.equal(await scalar('select question_text from questions where id=$1',[question]),originalBefore.question_text);
await assert.rejects(publish(copyId,stale));
assert.equal(await scalar('select status from quiz_sets where id=$1',[copyId]),'draft');
await db.query("update questions set review_status='pending_review' where id=$1",[copiedRow.id]);
await assert.rejects(publish(copyId,(await state(copyId)).publication_token));
await db.query("update questions set review_status='approved' where id=$1",[copiedRow.id]);
const publishToken=(await state(copyId)).publication_token;
await publish(copyId,publishToken);
await publish(copyId,publishToken);
assert.equal(await scalar("select count(*)::int from events where event_type='quiz.published'"),1,'lost response replay does not publish twice');
assert.equal(await scalar('select total_marks from quiz_variants where quiz_set_id=$1',[copyId]),'2');
for (const sql of ["update questions set question_text='Changed' where id=$1", "update questions set release_locked=false where id=$1", "update questions set figure_id=null where id=$1", "delete from questions where id=$1"]) {
  await assert.rejects(db.query(sql,[copiedRow.id]));
}
await assert.rejects(db.query('update quiz_variant_questions set order_index=9 where question_id=$1',[copiedRow.id]));
await assert.rejects(db.query('update quiz_variants set time_limit_minutes=3 where quiz_set_id=$1',[copyId]));
await db.query("update quiz_sets set status='archived',published_at=null where id=$1",[copyId]);
await assert.rejects(publish(copyId,(await state(copyId)).publication_token));
await db.query("update quiz_sets set status='draft' where id=$1",[copyId]);
await publish(copyId,(await state(copyId)).publication_token);
const grandchild=await copy(copyId);
assert.equal(await scalar('select q.source_quiz_id from questions q join quiz_variant_questions l on l.question_id=q.id join quiz_variants v on v.id=l.variant_id where v.quiz_set_id=$1',[grandchild.quiz_set_id]),source);
await assert.rejects(scalar('select copy_quiz_draft($1,$2,$3,$4,$5)',[source,uuid(),actor,uuid(),'Bad tenant']));
await assert.rejects(scalar('select copy_quiz_draft($1,$2,$3,$4,$5)',[source,tenant,uuid(),uuid(),'Bad owner']));
await db.query('delete from teacher_subjects where teacher_id=$1',[actor]);
await assert.rejects(copy(source));
await db.query('insert into teacher_subjects(tenant_id,teacher_id,subject_id) values($1,$2,$3)',[tenant,actor,subject]);
// A failure after the destination row is inserted rolls back the entire copy.
await db.query('update questions set created_by=null where id=$1',[question]);
const before=await scalar('select count(*)::int from quiz_sets');
await assert.rejects(copy(source));
assert.equal(await scalar('select count(*)::int from quiz_sets'),before);
await db.exec('set role authenticated');
await assert.rejects(db.query('select * from quiz_copy_requests'));
await assert.rejects(state(source));
await assert.rejects(copy(source));
await db.exec('reset role');
assert.deepEqual(await scalar('select to_jsonb(a) from quiz_attempts a where id=$1',[attempt]),historicalAttempt);
assert.equal(await scalar("select count(*)::int from events where event_type='question.generated'"),0,'copies do not inflate AI generation analytics');
assert.equal(await scalar("select count(*)::int from events where event_type='quiz.duplicated'"),2,'retry replay records no duplicate event');
console.log('PASS: migration reruns, copy replay, independent edits, figure/provenance preservation, atomic rollback, stale publication, immutable release, archive/restore, tenant and subject access, browser denial');
await db.close();
