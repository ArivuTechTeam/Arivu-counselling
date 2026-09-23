// Isolated Postgres integration tests. No connection string or hosted DB access.
// Install @electric-sql/pglite@0.3.14 under .tmp/pg-test, then run with Node.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

process.on("uncaughtException", error => { console.error(error.message); process.exit(1); });

const db = new PGlite();
const schema = fs.readFileSync("migrations/schema.sql", "utf8");
await db.exec("create role anon; create role authenticated; create role service_role bypassrls; create schema auth; create table auth.users(id uuid primary key);");
for (const type of schema.matchAll(/^create type .*?;$/gm)) await db.exec(type[0]);
await db.exec("alter type question_source add value 'extracted';");
for (const name of ["tenants", "profiles", "catalog_courses", "catalog_course_levels", "catalog_course_subjects", "courses", "course_levels", "subjects", "teacher_subjects", "chapters", "topics", "documents", "ai_extraction_jobs", "questions", "quiz_sets", "quiz_variants", "quiz_variant_questions", "quiz_generation_jobs"]) {
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
const request = {document_id:doc,subject_id:subject,chapter_id:chapter};
const enqueue = (key=uuid(), hash="same", kind="extraction") => scalar(
  "select enqueue_faculty_job($1,$2,$3,$4,$5,$6,10)",[tenant,actor,key,kind,request,hash]);
const claim = () => scalar("select claim_faculty_job()");
const update = (job,action,payload=null) => scalar("select update_faculty_job($1,$2,$3,$4,$5,$6)",
  [job.id,tenant,actor,job.lease_token,action,payload]);
const finish = job => scalar("select finish_faculty_job($1,$2)",[job.id,job.lease_token]);
const expire = job => db.query("update faculty_jobs set lease_expires_at=now()-interval '1 second' where id=$1",[job.id]);
const payload = {title:"Accounts",variant_type:"mixed",source:"extracted",provider:"fixture",
  import_summary:{candidates:1,imported:1,skipped:0,issues:[],coverage_verified:false},
  questions:[{type:"mcq_single",question_text:"Assets of 100 less liabilities of 40 equal what equity?",
    options:[{id:"A",text:"60"},{id:"B",text:"140"}],correct_answer:"A",marks:1,difficulty:"easy",confidence:0.9}]};

const key=uuid(), first=await enqueue(key);
assert.equal((await enqueue(key)).id,first.id);
assert.equal(await scalar("select n from quota_calls"),1,"replays do not consume quota");
assert.equal((await enqueue(key,"different")).conflict,true);
let claimed=await claim();
assert.equal(claimed.id,first.id);
assert.equal(await update(claimed,"heartbeat"),true);
await expire(claimed);
let replacement=await claim();
assert.notEqual(replacement.lease_token,claimed.lease_token);
assert.equal(await update(claimed,"checkpoint",payload),false,"late worker cannot save");
await assert.rejects(finish(claimed));
await update(replacement,"checkpoint",payload);
const result=await finish(replacement);
assert.equal((await finish(replacement)).quiz_set_id,result.quiz_set_id,"lost response replay is idempotent");
assert.equal(await scalar("select count(*)::int from quiz_sets"),1);
assert.equal(await scalar("select count(*)::int from questions where review_status='pending_review'"),1);
assert.deepEqual(await scalar("select raw_output->'import_summary' from ai_extraction_jobs"),payload.import_summary);

// Failure halfway through saving must roll back every result row and completion.
await enqueue(); claimed=await claim();
await update(claimed,"checkpoint",{...payload,questions:[...payload.questions,{...payload.questions[0],type:"invalid"}]});
await assert.rejects(finish(claimed));
assert.equal(await scalar("select count(*)::int from quiz_sets"),1);
assert.equal(await scalar("select count(*)::int from questions"),1);
assert.equal(await update(claimed,"cancel"),true);
await assert.rejects(finish(claimed));

// Two per tenant, recovery from saved checkpoint, and bounded crash retries.
await enqueue(); await enqueue(); await enqueue();
const a=await claim(), b=await claim();
assert.ok(a && b); assert.equal(await claim(),null);
await update(a,"checkpoint",payload); await expire(a);
const resumed=await claim(); assert.deepEqual(resumed.checkpoint,payload);
await finish(resumed); await update(b,"cancel");
claimed=await claim();
for(let attempt=1;attempt<=3;attempt++) {
  assert.equal(claimed.attempts,attempt); await expire(claimed);
  claimed=await claim();
}
assert.equal(claimed,null);
assert.equal(await scalar("select count(*)::int from faculty_jobs where status='failed'"),1);

// Service-only boundary: browser roles cannot call queue functions or read rows.
await db.exec("set role authenticated");
await assert.rejects(db.query("select * from faculty_jobs"));
await assert.rejects(db.query("select claim_faculty_job()"));
await db.exec("reset role");

// Generation preserves topics, numerical answers, and the existing analytics ledger.
await enqueue(uuid(),"generated","blueprint"); claimed=await claim();
const generated={...payload,source:"ai_generated",chapter_name:"Financial statements",selected_topics:["Equity"],
  questions:[{...payload.questions[0],type:"numerical",options:null,topic:"Equity",
    correct_answer:{value:60,tolerance:0},verification_status:"verified",verification_warnings:[]}]};
await update(claimed,"checkpoint",generated);
const generatedResult=await finish(claimed);
assert.deepEqual(generatedResult.questions[0].correct_answer,{value:60,tolerance:0});
assert.equal(await scalar("select count(*)::int from events where event_type='question.generated'"),1);
assert.equal(await scalar("select count(*)::int from questions where topic_id is not null"),1);

// Revoking access after preparation rolls back publication of the result.
await enqueue(); claimed=await claim(); await update(claimed,"checkpoint",payload);
await db.query("update tenants set is_active=false where id=$1",[tenant]);
await assert.rejects(finish(claimed));
assert.equal(await scalar("select status from faculty_jobs where id=$1",[claimed.id]),"running");
await assert.rejects(enqueue());
console.log("PASS: idempotency, quota replay, leases, atomic rollback, cancellation, checkpoint recovery, tenant cap, retry exhaustion, authorization, generated topics/answers/events");
await db.close();
