// Isolated migration-74 correctness and privilege checks; no live Supabase use.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create type public.user_role as enum (
    'super_admin', 'institution_admin', 'teacher', 'student'
  );
  create table public.tenants(id uuid primary key, name text not null);
  create table public.profiles(
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id) on delete cascade,
    role public.user_role not null,
    full_name text,
    unique(id, tenant_id)
  );
  grant select, update on public.profiles to service_role;
`);
await db.exec(fs.readFileSync("migrations/migration-60-student-contact.sql", "utf8"));
await db.exec(fs.readFileSync("migrations/migration-62-atomic-student-contact.sql", "utf8"));

const id = suffix => `00000000-0000-4000-8000-${suffix.padStart(12, "0")}`;
const tenant = id("1");
const student = id("2");
const secondStudent = id("3");
const teacher = id("4");
const institutionAdmin = id("5");
await db.query("insert into tenants(id,name) values($1,'Test Institute')", [tenant]);
await db.query(
  `insert into profiles(id,tenant_id,role,full_name) values
    ($1,$5,'student','Student One'),
    ($2,$5,'student','Student Two'),
    ($3,$5,'teacher','Faculty One'),
    ($4,$5,'institution_admin','Admin One')`,
  [student, secondStudent, teacher, institutionAdmin, tenant],
);
await db.query(
  `select public.submit_student_contact(
    $1,$2,'AAAAAAAAAAAA','support','quiz_issue','institution',
    'My quiz result needs help',null
  )`,
  [tenant, student],
);

await db.exec(fs.readFileSync("migrations/migration-74-role-aware-support.sql", "utf8"));

const historical = await db.query(
  "select requester_id,requester_role from student_contact_requests where reference='AAAAAAAAAAAA'",
);
assert.equal(historical.rows[0].requester_id, student);
assert.equal(historical.rows[0].requester_role, "student");

await db.exec("set role service_role");
const submit = async ({ requester, role, reference, route = "platform" }) => (
  await db.query(
    `select public.submit_contact_request(
      $1,$2,$3,$4,'support','general_support',$5,
      'Please help with this account',null
    ) as result`,
    [tenant, requester, role, reference, route],
  )
).rows[0].result;

assert.equal((await submit({ requester: teacher, role: "teacher", reference: "BBBBBBBBBBBB" })).allowed, true);
assert.equal((await submit({ requester: institutionAdmin, role: "institution_admin", reference: "CCCCCCCCCCCC" })).allowed, true);
await assert.rejects(
  () => submit({ requester: teacher, role: "institution_admin", reference: "DDDDDDDDDDDD" }),
  /support_profile_not_found/,
);
await assert.rejects(
  () => db.query(
    `insert into student_contact_requests(
      reference,tenant_id,requester_id,requester_role,kind,category,routed_to,message
    ) values('EEEEEEEEEEEE',$1,$2,'teacher','support','quiz_issue','institution','Invalid route test')`,
    [tenant, teacher],
  ),
  /student_contact_requests_route_check/,
);

const legacy = await db.query(
  `select public.submit_student_contact(
    $1,$2,'FFFFFFFFFFFF','support','quiz_issue','institution',
    'A second student needs help',null
  ) as result`,
  [tenant, secondStudent],
);
assert.equal(legacy.rows[0].result.allowed, true);

await db.exec("reset role; set role authenticated");
await assert.rejects(
  () => db.query("select * from student_contact_requests"),
  /permission denied/,
);
await assert.rejects(
  () => submit({ requester: teacher, role: "teacher", reference: "111111111111" }),
  /permission denied/,
);

await db.close();
console.log("Role-aware support SQL checks passed: history, roles, routing, compatibility and privileges.");
