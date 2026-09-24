// Isolated Postgres integration checks for migrations 52-57.
// No hosted database or credentials are used.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

process.on("uncaughtException", error => {
  console.error(error.message);
  process.exit(1);
});

const db = new PGlite();
const migrations = [52, 53, 54, 55, 56, 57].map(number => {
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
  -- Earlier teammate-branch scoring and paper-profile shapes. These deliberately
  -- omit tenant-qualified keys and make paper profiles course-wide.
  create table public.scoring_policies (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    name text not null,
    rules jsonb not null default '{}'::jsonb,
    created_by uuid references public.profiles(id),
    created_at timestamptz not null default now(),
    unique (tenant_id, name)
  );
  create table public.paper_profiles (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id),
    exam_body text,
    level text,
    paper text,
    assessment_year text,
    framework text,
    created_by uuid references public.profiles(id),
    created_at timestamptz not null default now(),
    unique (tenant_id, course_id)
  );
  -- Earlier teammate-branch shape: these tables already exist but batches are
  -- course-wide and none of the foreign keys are tenant-qualified.
  create table public.batches (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    course_id uuid not null references public.courses(id),
    name text not null,
    exam_session text,
    starts_on date,
    ends_on date,
    status text not null default 'active',
    created_by uuid references public.profiles(id),
    created_at timestamptz not null default now(),
    unique (tenant_id, course_id, name)
  );
  create table public.batch_memberships (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    batch_id uuid not null references public.batches(id),
    profile_id uuid not null references public.profiles(id),
    membership_role text not null default 'student',
    active boolean not null default true,
    valid_from date,
    valid_to date,
    created_at timestamptz not null default now(),
    unique (tenant_id, batch_id, profile_id)
  );
  create table public.quiz_assignments (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    quiz_set_id uuid not null references public.quiz_sets(id),
    batch_id uuid not null references public.batches(id),
    available_from timestamptz,
    available_to timestamptz,
    status text not null default 'active',
    created_by uuid references public.profiles(id),
    created_at timestamptz not null default now(),
    unique (tenant_id, quiz_set_id, batch_id)
  );
  create table public.practice_sessions (id uuid primary key default gen_random_uuid());

  insert into public.tenants(id, name)
  values ('00000000-0000-4000-8000-000000000001', 'Legacy tenant');
  insert into public.courses(id, tenant_id, name)
  values (
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000001',
    'Legacy course'
  );
  insert into public.course_levels(id, tenant_id, course_id, name)
  values (
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000002',
    'Only level'
  );
  insert into public.scoring_policies(tenant_id, name)
  values ('00000000-0000-4000-8000-000000000001', 'Legacy scoring');
  insert into public.paper_profiles(tenant_id, course_id, exam_body)
  values (
    '00000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000002',
    'Legacy body'
  );
`);

for (const migration of migrations) await db.exec(migration);
for (const migration of migrations) await db.exec(migration); // rerunnable rollout

assert.equal(
  (await db.query(`select is_nullable from information_schema.columns
    where table_schema='public' and table_name='batches' and column_name='course_level_id'`)).rows[0].is_nullable,
  "NO",
  "legacy batches must be upgraded to require a course level",
);
for (const constraint of [
  "batches_level_scope_fk",
  "batch_memberships_batch_tenant_fk",
  "batch_memberships_profile_tenant_fk",
  "quiz_assignments_quiz_tenant_fk",
  "quiz_assignments_batch_tenant_fk",
  "scoring_policies_creator_tenant_fk",
  "quiz_sets_scoring_policy_tenant_fk",
  "course_levels_exam_policy_tenant_fk",
  "paper_profiles_course_tenant_fk",
  "paper_profiles_level_scope_fk",
  "paper_profiles_creator_tenant_fk",
]) {
  assert.equal(
    (await db.query("select count(*)::int as count from pg_constraint where conname=$1", [constraint])).rows[0].count,
    1,
    `${constraint} must repair the legacy table shape`,
  );
}
assert.equal(
  (await db.query(`select course_level_id::text as course_level_id
    from public.paper_profiles where exam_body='Legacy body'`)).rows[0].course_level_id,
  "00000000-0000-4000-8000-000000000003",
  "legacy paper profiles must be upgraded to their sole course level",
);

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
await assert.rejects(
  db.query(
    "insert into batch_memberships(tenant_id,batch_id,profile_id) values($1,$2,$3)",
    [t1, batch, student],
  ),
  undefined,
  "a disabled tenant must not receive batch memberships",
);
await db.query(
  "update tenants set feature_flags=$1 where id=$2",
  [{ batches: true }, t1],
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

console.log("PASS: migrations 52-57 rerun, feature rollout, level scope, tenant FKs, attempt snapshots, browser denial");
await db.close();
