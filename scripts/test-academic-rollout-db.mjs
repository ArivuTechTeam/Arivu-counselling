// Isolated Postgres integration checks for migrations 52-56.
// No hosted database or credentials are used.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

process.on("uncaughtException", error => {
  console.error(error.message);
  process.exit(1);
});

const db = new PGlite();
const migrations = [52, 53, 54, 55, 56].map(number => {
  const filename = fs.readdirSync("migrations").find(name => name.startsWith(`migration-${number}-`));
  assert.ok(filename, `migration ${number}`);
  return fs.readFileSync(`migrations/${filename}`, "utf8");
});

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create role supabase_auth_admin;
  create schema auth;
  create type public.user_role as enum ('super_admin','institution_admin','teacher','student');
  create type public.attempt_status as enum ('in_progress','submitted','graded','abandoned');
  create table auth.users (
    id uuid primary key,
    raw_user_meta_data jsonb default '{}'::jsonb,
    raw_app_meta_data jsonb default '{}'::jsonb
  );
  create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
  create function public.current_tenant_id() returns uuid language sql stable as $$ select null::uuid $$;
  create function public.is_super_admin() returns boolean language sql stable as $$ select false $$;
  create function public.current_role_name() returns text language sql stable as $$ select null::text $$;
  create function public.is_staff() returns boolean language sql stable as $$ select false $$;

  create table public.tenants (
    id uuid primary key,
    name text not null,
    is_active boolean not null default true
  );
  create table public.profiles (
    id uuid primary key references auth.users(id),
    tenant_id uuid not null references public.tenants(id),
    role public.user_role not null,
    full_name text,
    unique (id, tenant_id)
  );
  create table public.courses (
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id),
    name text not null,
    unique (id, tenant_id)
  );
  create table public.course_levels (
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id),
    name text not null,
    is_active boolean not null default true,
    unique (id, tenant_id, course_id)
  );
  create table public.enrollments (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    profile_id uuid not null references public.profiles(id),
    course_id uuid not null references public.courses(id),
    course_level_id uuid,
    unique (profile_id, course_id),
    foreign key (course_level_id, tenant_id, course_id)
      references public.course_levels(id, tenant_id, course_id)
  );
  create table public.quiz_sets (
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id),
    unique (id, tenant_id)
  );
  create table public.quiz_attempts (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    variant_id uuid not null,
    student_id uuid not null,
    status public.attempt_status not null,
    started_at timestamptz,
    question_snapshot jsonb
  );
  create table public.practice_sessions (id uuid primary key default gen_random_uuid());
`);

for (const migration of migrations) await db.exec(migration);
for (const migration of migrations) await db.exec(migration); // rerunnable rollout

const uuid = () => crypto.randomUUID();
const t1 = uuid(), t2 = uuid(), admin = uuid(), student = uuid();
const c1 = uuid(), c2 = uuid(), l1 = uuid(), l2 = uuid(), otherLevel = uuid();
const quiz = uuid(), batch = uuid();
await db.query("insert into tenants(id,name) values($1,'One'),($2,'Two')", [t1, t2]);
await db.query("insert into auth.users(id) values($1),($2)", [admin, student]);
await db.query(
  "insert into profiles(id,tenant_id,role) values($1,$2,'institution_admin'),($3,$2,'student')",
  [admin, t1, student],
);
await db.query("insert into courses(id,tenant_id,name) values($1,$2,'CA'),($3,$4,'Other')", [c1, t1, c2, t2]);
await db.query(
  "insert into course_levels(id,tenant_id,course_id,name) values($1,$2,$3,'Foundation'),($4,$2,$3,'Final'),($5,$6,$7,'Other')",
  [l1, t1, c1, l2, otherLevel, t2, c2],
);
await db.query("insert into enrollments(tenant_id,profile_id,course_id,course_level_id) values($1,$2,$3,$4)", [t1, student, c1, l1]);
await db.query("insert into quiz_sets(id,tenant_id) values($1,$2)", [quiz, t1]);

await db.query(
  "insert into batches(id,tenant_id,course_id,course_level_id,name,created_by) values($1,$2,$3,$4,'2027',$5)",
  [batch, t1, c1, l1, admin],
);
await db.query(
  "insert into batch_memberships(tenant_id,batch_id,profile_id) values($1,$2,$3)",
  [t1, batch, student],
);
await assert.rejects(db.query(
  "insert into batches(tenant_id,course_id,course_level_id,name) values($1,$2,$3,'Invalid')",
  [t1, c1, otherLevel],
));

const policy = uuid();
await db.query(
  "insert into scoring_policies(id,tenant_id,name,rules,created_by) values($1,$2,'CA Foundation',$3,$4)",
  [policy, t1, { wrong_penalty: 0.25 }, admin],
);
await db.query("update course_levels set exam_scoring_policy_id=$1 where id=$2", [policy, l1]);
await assert.rejects(db.query("update course_levels set exam_scoring_policy_id=$1 where id=$2", [policy, otherLevel]));

await db.query(
  "insert into paper_profiles(tenant_id,course_id,course_level_id,exam_body,created_by) values($1,$2,$3,'ICAI',$4),($1,$2,$5,'ICAI',$4)",
  [t1, c1, l1, admin, l2],
);
assert.equal(
  (await db.query("select count(*)::int as count from paper_profiles where tenant_id=$1", [t1])).rows[0].count,
  2,
  "one course may have different profiles for different levels",
);
await assert.rejects(db.query(
  "insert into paper_profiles(tenant_id,course_id,course_level_id,exam_body) values($1,$2,$3,'Invalid')",
  [t1, c1, otherLevel],
));

const variant = uuid();
const attempt = (await db.query(
  "select create_limited_quiz_attempt($1,$2,$3,now(),2,$4,$5) as id",
  [t1, variant, student, [{ id: "q1" }], { wrong_penalty: 0.25 }],
)).rows[0].id;
assert.deepEqual(
  (await db.query("select scoring_policy_snapshot from quiz_attempts where id=$1", [attempt])).rows[0].scoring_policy_snapshot,
  { wrong_penalty: 0.25 },
);

await db.exec("set role authenticated");
for (const table of ["batches", "batch_memberships", "quiz_assignments", "scoring_policies", "paper_profiles"]) {
  await assert.rejects(db.query(`select * from ${table}`), undefined, `${table} must not be browser-readable`);
}
await db.exec("reset role");

console.log("PASS: migrations 52-56 rerun, level scope, tenant FKs, attempt snapshots, browser denial");
await db.close();
