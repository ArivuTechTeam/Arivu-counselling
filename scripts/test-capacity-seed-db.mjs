// Isolated integration check for the Release A1 synthetic capacity seed.
// No hosted database, network connection, credential, or real user is used.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const seed = fs.readFileSync("scripts/capacity-seed.sql", "utf8");

await db.exec(`
  create type public.question_type as enum ('mcq_single','mcq_multi','numerical','true_false','fill_blank','descriptive');
  create type public.question_source as enum ('ai_generated','manual');
  create type public.review_status as enum ('pending_review','approved','rejected','needs_edit');
  create type public.variant_type as enum ('theory','practical','mixed');
  create type public.quiz_status as enum ('draft','published','archived');

  create table public.tenants (
    id uuid primary key, name text not null, subdomain text not null unique,
    plan_tier text not null, is_active boolean not null
  );
  create table public.courses (
    id uuid primary key, tenant_id uuid not null references public.tenants(id), name text not null
  );
  create table public.course_levels (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id), name text not null,
    is_active boolean not null
  );
  create table public.subjects (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id),
    course_level_id uuid not null references public.course_levels(id), name text not null
  );
  create table public.chapters (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    subject_id uuid not null references public.subjects(id), name text not null, order_index int not null
  );
  create table public.quiz_sets (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    chapter_id uuid references public.chapters(id), subject_id uuid references public.subjects(id),
    title text not null, status public.quiz_status not null,
    published_at timestamptz
  );
  create table public.quiz_variants (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    quiz_set_id uuid not null references public.quiz_sets(id),
    variant_type public.variant_type not null, time_limit_minutes int, total_marks numeric
  );
  create table public.questions (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    chapter_id uuid references public.chapters(id), type public.question_type not null,
    question_text text not null, options jsonb, correct_answer jsonb not null,
    explanation text, difficulty text, marks numeric not null,
    source public.question_source not null, verification_status text not null,
    review_status public.review_status not null
  );
  create table public.quiz_variant_questions (
    id uuid primary key, tenant_id uuid not null references public.tenants(id),
    variant_id uuid not null references public.quiz_variants(id),
    question_id uuid not null references public.questions(id), order_index int not null,
    unique (variant_id, question_id)
  );
`);

await assert.rejects(db.exec(seed), /Capacity seed refused/);
await db.exec("rollback; set arivupro.capacity_seed_confirmed = 'STAGING_ONLY';");
await db.exec(seed);

const counts = {};
for (const table of [
  "tenants", "courses", "course_levels", "subjects", "chapters",
  "quiz_sets", "quiz_variants", "questions", "quiz_variant_questions",
]) {
  counts[table] = (await db.query(`select count(*)::int as count from public.${table}`)).rows[0].count;
}

assert.deepEqual(counts, {
  tenants: 2,
  courses: 2,
  course_levels: 2,
  subjects: 4,
  chapters: 8,
  quiz_sets: 40,
  quiz_variants: 40,
  questions: 200,
  quiz_variant_questions: 200,
});
assert.equal(
  (await db.query("select count(*)::int as count from quiz_sets where status = 'published'")).rows[0].count,
  16,
);
assert.equal(
  (await db.query(`
    select count(*)::int as count
    from quiz_variant_questions links
    join quiz_variants variants on variants.id = links.variant_id
    join questions on questions.id = links.question_id
    where links.tenant_id <> variants.tenant_id
       or links.tenant_id <> questions.tenant_id
  `)).rows[0].count,
  0,
);

await db.exec("set arivupro.capacity_seed_confirmed = 'STAGING_ONLY';");
await db.exec(seed); // deterministic IDs make the seed repeatable.
assert.equal((await db.query("select count(*)::int as count from questions")).rows[0].count, 200);

await db.close();
console.log("capacity seed database integration checks passed");
