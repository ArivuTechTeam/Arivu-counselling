// Isolated SQL correctness/privilege checks; no real Supabase connection.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
await db.exec(`
  create role anon; create role authenticated; create role service_role bypassrls;
  create table public.tenants(id uuid primary key);
  create table public.documents(id uuid primary key);
  create table public.quiz_sets(id uuid primary key, tenant_id uuid, title text);
  create table public.quiz_generation_jobs(id uuid primary key);
  grant select on public.quiz_sets to service_role;
`);
await db.exec(fs.readFileSync("migrations/migration-42-api-call-logs.sql", "utf8"));
const migration = fs.readFileSync("migrations/migration-73-ai-quiz-cost-workflows.sql", "utf8");
await db.exec(migration);
await db.exec(migration);
const id = suffix => `00000000-0000-4000-8000-${suffix.padStart(12, "0")}`;
const tenant = id("1"), document = id("2"), run1 = id("3"), run2 = id("4"), quiz = id("5");
await db.query("insert into tenants values($1)", [tenant]);
await db.query("insert into documents values($1)", [document]);
await db.query("insert into quiz_sets values($1,$2,'Test quiz')", [quiz,tenant]);
await db.query(`insert into ai_quiz_workflows(id,tenant_id,document_id,quiz_set_id,kind,status)
  values($1,$3,$4,$5,'generation','completed'),($2,$3,$4,null,'generation','failed')`, [run1,run2,tenant,document,quiz]);
for (let i = 0; i < 65; i++) {
  await db.query(`insert into api_call_logs(tenant_id,document_id,workflow_id,call_type,provider,model,
    cost_usd,cost_inr,latency_ms,status,input_tokens,output_tokens)
    values($1,$2,$3,'quiz_generation','deepseek','deepseek-flash',0.01,0.83,100,'success',100,20)`, [tenant,document,run1]);
}
await db.query(`insert into api_call_logs(tenant_id,document_id,workflow_id,call_type,provider,model,
  cost_usd,latency_ms,status) values($1,$2,$3,'quiz_generation','gemini','unknown',null,200,'error')`, [tenant,document,run2]);
await db.query(`insert into api_call_logs(tenant_id,document_id,call_type,provider,model,
  cost_usd,latency_ms,status) values($1,$2,'question_regeneration','deepseek','deepseek-flash',0.02,200,'success')`, [tenant,document]);
const page = async (sql = "select ai_quiz_cost_page() as data", params = []) =>
  (await db.query(sql, params)).rows[0].data;
let result = await page();
assert.equal(result.total, 3);
assert.equal(result.call_count, 67);
assert.equal(result.unpriced_calls, 1);
assert.equal(result.cost_usd, 0.67);
const first = result.items.find(row => row.workflow_id === run1);
assert.equal(first.call_count, 65); // Never truncated to a 50-call API page.
assert.equal(first.cost_usd, 0.65);
assert.equal(first.quiz_set_id, quiz);
assert.equal(first.quiz_title, "Test quiz");
assert.equal(first.stages[0].calls, 65);
assert.equal(result.items.find(row => row.workflow_id === run2).unpriced_calls, 1);
assert.equal(result.items.find(row => row.kind === "legacy").cost_usd, 0.02);
result = await page("select ai_quiz_cost_page(p_kind=>'generation',p_page_size=>1) as data");
assert.equal(result.total, 2);
assert.equal(result.items.length, 1);
assert.equal(result.call_count, 66);
assert.equal(result.cost_usd, 0.65); // Overview total independent of group pagination.
result = await page("select ai_quiz_cost_page(p_status=>'error') as data");
assert.equal(result.call_count, 1);
assert.equal(result.cost_usd, null); // Unknown pricing must not display a fake zero.
result = await page("select ai_quiz_cost_page(p_tenant=>$1) as data", [id("999")]);
assert.equal(result.total, 0);
assert.deepEqual(result.items, []);
for (const role of ["anon","authenticated"]) {
  await db.exec(`set role ${role}`);
  await assert.rejects(() => page(), /permission denied/);
  await assert.rejects(() => db.query("select * from ai_quiz_workflows"), /permission denied/);
  await db.exec("reset role");
}
await db.exec("set role service_role");
assert.equal((await page()).total, 3);
await db.close();
console.log("AI quiz cost SQL checks passed: complete totals, run separation, filters, unknown costs and privileges.");
