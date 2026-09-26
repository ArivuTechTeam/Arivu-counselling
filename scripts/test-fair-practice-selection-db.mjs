// Isolated PostgreSQL contract, fairness, and authorization checks for migration 70.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration = fs.readFileSync(
  "migrations/migration-70-fair-practice-selection.sql",
  "utf8",
);

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create type public.user_role as enum ('super_admin','institution_admin','teacher','student');
  create type public.question_type as enum ('mcq_single','mcq_multi','true_false','numerical','fill_blank');
  create type public.review_status as enum ('pending_review','approved','rejected','needs_edit');
  create type public.quiz_status as enum ('draft','published','archived');
  create table public.tenants (id uuid primary key);
  create table public.profiles (
    id uuid primary key, tenant_id uuid not null, role public.user_role not null
  );
  create table public.subjects (
    id uuid primary key, tenant_id uuid not null, course_id uuid not null,
    course_level_id uuid, name text not null
  );
  create table public.enrollments (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    profile_id uuid not null, course_id uuid not null, course_level_id uuid
  );
  create table public.chapters (
    id uuid primary key, tenant_id uuid not null, subject_id uuid not null,
    name text not null
  );
  create table public.questions (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    chapter_id uuid, type public.question_type not null,
    difficulty text default 'medium',
    review_status public.review_status not null default 'pending_review',
    release_locked boolean not null default false,
    content_version bigint not null default 1
  );
  create table public.quiz_sets (
    id uuid primary key, tenant_id uuid not null, subject_id uuid,
    status public.quiz_status not null, audience_mode text not null default 'legacy_course'
  );
  create table public.quiz_variants (
    id uuid primary key, tenant_id uuid not null, quiz_set_id uuid not null
  );
  create table public.quiz_variant_questions (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    variant_id uuid not null, question_id uuid not null
  );
  create table public.batch_memberships (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    batch_id uuid not null, profile_id uuid not null, active boolean not null,
    valid_from date, valid_to date
  );
  create table public.quiz_assignments (
    id uuid primary key default gen_random_uuid(), tenant_id uuid not null,
    quiz_set_id uuid not null, batch_id uuid not null, status text not null,
    available_from timestamptz, available_to timestamptz
  );

  create or replace function public.guard_released_question() returns trigger
  language plpgsql set search_path=public as $$
  begin
    if tg_op='DELETE' then
      if old.release_locked then
        raise exception 'quiz_locked' using errcode='PT409';
      end if;
      return old;
    end if;
    if old.release_locked and (
      (to_jsonb(new)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])
      is distinct from
      (to_jsonb(old)-array['created_by','reviewed_by','origin_question_id','source_quiz_id','content_version'])
    ) then
      raise exception 'quiz_locked' using errcode='PT409';
    end if;
    new.content_version := old.content_version + 1;
    return new;
  end $$;
  create trigger guard_released_question
    before update or delete on public.questions
    for each row execute function public.guard_released_question();
`);

const ids = {
  tenant: "00000000-0000-4000-8000-000000000001",
  otherTenant: "00000000-0000-4000-8000-000000000002",
  student: "00000000-0000-4000-8000-000000000010",
  outsider: "00000000-0000-4000-8000-000000000011",
  otherStudent: "00000000-0000-4000-8000-000000000012",
  teacher: "00000000-0000-4000-8000-000000000013",
  course: "00000000-0000-4000-8000-000000000020",
  otherCourse: "00000000-0000-4000-8000-000000000021",
  level: "00000000-0000-4000-8000-000000000030",
  subject: "00000000-0000-4000-8000-000000000040",
  unenrolledSubject: "00000000-0000-4000-8000-000000000041",
  mainChapter: "00000000-0000-4000-8000-000000000050",
  preexistingChapter: "00000000-0000-4000-8000-000000000051",
  draftChapter: "00000000-0000-4000-8000-000000000052",
  archivedChapter: "00000000-0000-4000-8000-000000000053",
  assignedChapter: "00000000-0000-4000-8000-000000000054",
  expiredChapter: "00000000-0000-4000-8000-000000000055",
  legacyChapter: "00000000-0000-4000-8000-000000000056",
  unenrolledChapter: "00000000-0000-4000-8000-000000000057",
  otherTenantChapter: "00000000-0000-4000-8000-000000000058",
  reviewChapter: "00000000-0000-4000-8000-000000000059",
};

await db.query("insert into tenants(id) values($1),($2)", [ids.tenant, ids.otherTenant]);
await db.query(`insert into profiles(id,tenant_id,role) values
  ($1,$2,'student'),($3,$2,'student'),($4,$5,'student'),($6,$2,'teacher')`,
  [ids.student, ids.tenant, ids.outsider, ids.otherStudent, ids.otherTenant, ids.teacher]);
await db.query(`insert into subjects(id,tenant_id,course_id,course_level_id,name) values
  ($1,$2,$3,$4,'Enrolled'),($5,$2,$6,$4,'Not enrolled')`,
  [ids.subject, ids.tenant, ids.course, ids.level, ids.unenrolledSubject, ids.otherCourse]);
await db.query(`insert into enrollments(tenant_id,profile_id,course_id,course_level_id) values
  ($1,$2,$3,$4),($1,$5,$3,$4),($1,$6,$3,$4)`,
  [ids.tenant, ids.student, ids.course, ids.level, ids.outsider, ids.teacher]);
for (const [id, subject, name] of [
  [ids.mainChapter, ids.subject, "Main"],
  [ids.preexistingChapter, ids.subject, "Preexisting"],
  [ids.draftChapter, ids.subject, "Draft"],
  [ids.archivedChapter, ids.subject, "Archived"],
  [ids.assignedChapter, ids.subject, "Assigned"],
  [ids.expiredChapter, ids.subject, "Expired"],
  [ids.legacyChapter, ids.subject, "Legacy"],
  [ids.unenrolledChapter, ids.unenrolledSubject, "Unenrolled"],
  [ids.reviewChapter, ids.subject, "Review status"],
]) {
  await db.query(
    "insert into chapters(id,tenant_id,subject_id,name) values($1,$2,$3,$4)",
    [id, ids.tenant, subject, name],
  );
}
await db.query(
  "insert into chapters(id,tenant_id,subject_id,name) values($1,$2,$3,'Other tenant')",
  [ids.otherTenantChapter, ids.otherTenant, ids.unenrolledSubject],
);
await db.query(`insert into questions(
  tenant_id,chapter_id,type,difficulty,review_status,release_locked
)
  values($1,$2,'mcq_single','medium','approved',true)`,
  [ids.tenant, ids.preexistingChapter]);

await db.exec(migration);
await db.exec(migration);

const preexisting = await db.query(
  `select sampling_key is not null as filled, content_version
   from questions where chapter_id=$1`,
  [ids.preexistingChapter],
);
assert.equal(preexisting.rows[0].filled, true);
assert.equal(Number(preexisting.rows[0].content_version), 1);
const trigger = await db.query(`select tgenabled
  from pg_trigger
  where tgrelid='public.questions'::regclass
    and tgname='guard_released_question'`);
assert.equal(trigger.rows[0].tgenabled, "O");
await assert.rejects(
  db.query("update questions set difficulty='hard' where chapter_id=$1", [ids.preexistingChapter]),
  /quiz_locked/,
);

await db.query(`insert into questions(
  tenant_id,chapter_id,type,difficulty,review_status,sampling_key
)
select $1,$2,'mcq_single','medium','approved',series::bigint
from generate_series(1,2505) series`, [ids.tenant, ids.mainChapter]);

const sample = async ({
  student = ids.student,
  limit = 10,
  start = 0,
  batches = false,
  subject = ids.subject,
  chapter = ids.mainChapter,
  difficulty = null,
  type = null,
} = {}) => (
  await db.query(`select public.select_practice_question_ids_page(
    $1::uuid,$2::uuid,$3::integer,$4::bigint,$5::boolean,$6::uuid,$7::uuid,$8::text,$9::text
  ) as value`, [
    ids.tenant, student, limit, start, batches, subject, chapter, difficulty, type,
  ])
).rows[0].value;

const samplingKeys = async (questionIds) => {
  const keys = [];
  for (const questionId of questionIds) {
    const row = await db.query(
      "select sampling_key::text as key from questions where id=$1::uuid",
      [questionId],
    );
    keys.push(Number(row.rows[0].key));
  }
  return keys;
};

const beyondOldPool = await sample({ start: 2400 });
assert.equal(beyondOldPool.question_ids.length, 10);
assert.deepEqual(await samplingKeys(beyondOldPool.question_ids), [
  2400, 2401, 2402, 2403, 2404, 2405, 2406, 2407, 2408, 2409,
]);

const wrapped = await sample({ start: 2503 });
assert.deepEqual(await samplingKeys(wrapped.question_ids), [
  2503, 2504, 2505, 1, 2, 3, 4, 5, 6, 7,
]);

const coverageBuckets = new Set();
for (let start = 1; start <= 2500; start += 125) {
  const page = await sample({ start, limit: 1 });
  const [key] = await samplingKeys(page.question_ids);
  coverageBuckets.add(Math.min(4, Math.floor((key - 1) / 501)));
}
assert.deepEqual([...coverageBuckets].sort(), [0, 1, 2, 3, 4]);

const insertQuestion = async (chapter, key, reviewStatus = "approved", type = "mcq_single") => (
  await db.query(`insert into questions(
    tenant_id,chapter_id,type,difficulty,review_status,sampling_key
  ) values($1,$2,$3::public.question_type,'medium',$4::public.review_status,$5)
  returning id`, [ids.tenant, chapter, type, reviewStatus, key])
).rows[0].id;

const typedIds = [];
for (const key of [4001, 4002, 4003]) {
  typedIds.push(await insertQuestion(ids.mainChapter, key, "approved", "true_false"));
}
const typed = await sample({ start: 0, limit: 5, type: "true_false" });
assert.deepEqual(typed.question_ids, typedIds);
assert.equal(typed.available, 3);

const hardIds = [];
for (const key of [4101, 4102]) {
  const question = await db.query(`insert into questions(
    tenant_id,chapter_id,type,difficulty,review_status,sampling_key
  ) values($1,$2,'mcq_single','hard','approved',$3) returning id`,
  [ids.tenant, ids.mainChapter, key]);
  hardIds.push(question.rows[0].id);
}
const hard = await sample({ start: 0, limit: 5, difficulty: "hard" });
assert.deepEqual(hard.question_ids, hardIds);
assert.equal(hard.available, 2);

const linkQuestion = async (questionId, status, audience, suffix, window = "active") => {
  const quiz = `10000000-0000-4000-8000-0000000000${suffix}`;
  const variant = `20000000-0000-4000-8000-0000000000${suffix}`;
  await db.query(`insert into quiz_sets(id,tenant_id,subject_id,status,audience_mode)
    values($1,$2,$3,$4::public.quiz_status,$5)`,
    [quiz, ids.tenant, ids.subject, status, audience]);
  await db.query("insert into quiz_variants(id,tenant_id,quiz_set_id) values($1,$2,$3)",
    [variant, ids.tenant, quiz]);
  await db.query(`insert into quiz_variant_questions(tenant_id,variant_id,question_id)
    values($1,$2,$3)`, [ids.tenant, variant, questionId]);
  if (audience === "assigned_batches") {
    const batch = `30000000-0000-4000-8000-0000000000${suffix}`;
    await db.query(`insert into quiz_assignments(
      tenant_id,quiz_set_id,batch_id,status,available_from,available_to
    ) values($1,$2,$3,'active',now()-interval '1 day',
      case when $4='expired' then now()-interval '1 hour' else now()+interval '1 day' end)`,
      [ids.tenant, quiz, batch, window]);
    await db.query(`insert into batch_memberships(
      tenant_id,batch_id,profile_id,active,valid_from,valid_to
    ) values($1,$2,$3,true,current_date-1,current_date+1)`,
      [ids.tenant, batch, ids.student]);
  }
};

const draft = await insertQuestion(ids.draftChapter, 3001);
await linkQuestion(draft, "draft", "legacy_course", "01");
const archived = await insertQuestion(ids.archivedChapter, 3002);
await linkQuestion(archived, "archived", "legacy_course", "02");
const assigned = await insertQuestion(ids.assignedChapter, 3003);
await linkQuestion(assigned, "published", "assigned_batches", "03");
const expired = await insertQuestion(ids.expiredChapter, 3004);
await linkQuestion(expired, "published", "assigned_batches", "04", "expired");
const legacy = await insertQuestion(ids.legacyChapter, 3005);
await linkQuestion(legacy, "published", "legacy_course", "05");
await insertQuestion(ids.unenrolledChapter, 3006);
await insertQuestion(ids.mainChapter, 3007, "pending_review");
await insertQuestion(ids.reviewChapter, 3008, "pending_review");
await insertQuestion(ids.reviewChapter, 3009, "rejected");
await db.query(`insert into questions(
  tenant_id,chapter_id,type,difficulty,review_status,sampling_key
) values($1,$2,'mcq_single','medium','approved',3010)`,
  [ids.otherTenant, ids.otherTenantChapter]);

assert.deepEqual((await sample({ chapter: ids.draftChapter })).question_ids, []);
assert.deepEqual((await sample({ chapter: ids.archivedChapter })).question_ids, []);
assert.deepEqual(
  (await sample({ chapter: ids.assignedChapter, batches: true })).question_ids,
  [assigned],
);
assert.deepEqual(
  (await sample({ student: ids.outsider, chapter: ids.assignedChapter, batches: true })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ student: ids.outsider, chapter: ids.assignedChapter, batches: false })).question_ids,
  [assigned],
);
assert.deepEqual(
  (await sample({ chapter: ids.expiredChapter, batches: true })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ student: ids.outsider, chapter: ids.legacyChapter, batches: true })).question_ids,
  [legacy],
);
assert.deepEqual(
  (await sample({ chapter: ids.unenrolledChapter })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ chapter: ids.reviewChapter })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ subject: null, chapter: ids.otherTenantChapter })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ student: ids.otherStudent })).question_ids,
  [],
);
assert.deepEqual(
  (await sample({ student: ids.teacher })).question_ids,
  [],
);
assert.equal((await sample({ limit: 1000 })).question_ids.length, 100);

for (const index of [
  "idx_questions_practice_chapter_sample",
  "idx_questions_practice_chapter_type_sample",
  "idx_vq_tenant_question_variant",
]) {
  const exists = await db.query(
    "select to_regclass('public.' || $1) is not null as found",
    [index],
  );
  assert.equal(exists.rows[0].found, true, index);
}

const signature = "public.select_practice_question_ids_page(uuid,uuid,integer,bigint,boolean,uuid,uuid,text,text)";
assert.equal((await db.query(
  "select has_function_privilege('anon',$1,'EXECUTE') allowed", [signature],
)).rows[0].allowed, false);
assert.equal((await db.query(
  "select has_function_privilege('authenticated',$1,'EXECUTE') allowed", [signature],
)).rows[0].allowed, false);
assert.equal((await db.query(
  "select has_function_privilege('service_role',$1,'EXECUTE') allowed", [signature],
)).rows[0].allowed, true);

console.log("migration 70 fair practice selection checks passed");
await db.close();
