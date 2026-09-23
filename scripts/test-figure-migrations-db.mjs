// Isolated regression for migrations 49-50 against the earlier branch shape.
// No hosted database or credentials are used.
import assert from "node:assert/strict";
import fs from "node:fs";
import { PGlite } from "../.tmp/pg-test/node_modules/@electric-sql/pglite/dist/index.js";

const db = new PGlite();
const migration49 = fs.readFileSync("migrations/migration-49-document-figures.sql", "utf8");
const migration50 = fs.readFileSync("migrations/migration-50-question-figure-link.sql", "utf8");

await db.exec(`
  create role anon;
  create role authenticated;
  create role service_role bypassrls;
  create schema storage;
  create table storage.buckets (
    id text primary key,
    name text not null,
    public boolean not null,
    file_size_limit bigint,
    allowed_mime_types text[]
  );
  create function public.current_tenant_id() returns uuid language sql stable
    as $$ select null::uuid $$;
  create function public.is_staff() returns boolean language sql stable
    as $$ select false $$;
  create table public.tenants (id uuid primary key);
  create table public.documents (
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id)
  );
  create table public.questions (
    id uuid primary key,
    tenant_id uuid not null references public.tenants(id)
  );

  -- Shape produced by the earlier branch: primary key on id, but no explicit
  -- candidate key for the tenant-qualified foreign key in migration 50.
  create table public.document_figures (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants(id),
    document_id uuid not null,
    page int,
    bbox jsonb,
    label text,
    caption text,
    nearby_text text,
    storage_path text not null,
    width int,
    height int,
    created_at timestamptz not null default now()
  );
`);

for (const migration of [migration49, migration50, migration49, migration50]) {
  await db.exec(migration);
}

assert.equal(
  (await db.query(`
    select count(*)::int as count
    from pg_indexes
    where schemaname = 'public'
      and tablename = 'document_figures'
      and indexname = 'uq_document_figures_id_tenant'
  `)).rows[0].count,
  1,
);
assert.equal(
  (await db.query(`
    select count(*)::int as count
    from pg_constraint
    where conname = 'questions_figure_tenant_fk'
  `)).rows[0].count,
  1,
);

const tenant1 = crypto.randomUUID(), tenant2 = crypto.randomUUID();
const document = crypto.randomUUID(), figure = crypto.randomUUID();
const ownQuestion = crypto.randomUUID(), otherQuestion = crypto.randomUUID();
await db.query("insert into tenants(id) values($1),($2)", [tenant1, tenant2]);
await db.query("insert into documents(id,tenant_id) values($1,$2)", [document, tenant1]);
await db.query(
  "insert into document_figures(id,tenant_id,document_id,storage_path) values($1,$2,$3,'figure.png')",
  [figure, tenant1, document],
);
await db.query(
  "insert into questions(id,tenant_id) values($1,$2),($3,$4)",
  [ownQuestion, tenant1, otherQuestion, tenant2],
);
await db.query("update questions set figure_id=$1 where id=$2", [figure, ownQuestion]);
await assert.rejects(
  db.query("update questions set figure_id=$1 where id=$2", [figure, otherQuestion]),
  undefined,
  "a figure from another tenant must remain impossible to attach",
);

console.log("PASS: migrations 49-50 repair the earlier table shape, rerun, and preserve tenant isolation");
await db.close();
