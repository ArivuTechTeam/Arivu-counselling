// Applies all DB migrations to the local Miniflare D1 SQLite file.
// Run: node scripts/migrate-local.mjs
import { DatabaseSync } from 'node:sqlite';
import { readdirSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';

const stateDir = '.wrangler/state/v3/d1/miniflare-D1DatabaseObject';
if (!existsSync(stateDir)) {
  console.log('No local D1 state found. Start `pnpm dev` once first, then re-run this script.');
  process.exit(1);
}

const files = readdirSync(stateDir).filter(f => f.endsWith('.sqlite') && !f.includes('metadata'));
if (!files.length) {
  console.log('No SQLite file found in', stateDir);
  process.exit(1);
}

const dbPath = join(stateDir, files[0]);
console.log('Using DB:', dbPath);
const db = new DatabaseSync(dbPath);

// ── Migration 0000: create core tables ───────────────────────────────────────
db.exec(`
CREATE TABLE IF NOT EXISTS requests (
  id text PRIMARY KEY NOT NULL,
  user_id text NOT NULL,
  name text NOT NULL,
  email text NOT NULL,
  phone text NOT NULL,
  course text NOT NULL,
  level text NOT NULL,
  slot text NOT NULL,
  concern text NOT NULL,
  status text DEFAULT 'Requested' NOT NULL,
  notes text DEFAULT '' NOT NULL,
  created text NOT NULL
);
CREATE TABLE IF NOT EXISTS staff_owner (
  id text PRIMARY KEY NOT NULL,
  user_id text NOT NULL
);
`);

// ── Migration 0001: add new columns ──────────────────────────────────────────
const cols = db.prepare('PRAGMA table_info(requests)').all().map(c => c.name);
if (!cols.includes('meet_link'))    db.exec("ALTER TABLE requests ADD COLUMN meet_link text DEFAULT '' NOT NULL");
if (!cols.includes('otp_verified')) db.exec('ALTER TABLE requests ADD COLUMN otp_verified integer DEFAULT 0 NOT NULL');
if (!cols.includes('email_sent'))   db.exec('ALTER TABLE requests ADD COLUMN email_sent integer DEFAULT 0 NOT NULL');

db.exec(`
CREATE TABLE IF NOT EXISTS otp_store (
  phone text PRIMARY KEY NOT NULL,
  code text NOT NULL,
  expires_at text NOT NULL,
  attempts integer DEFAULT 0 NOT NULL
);
`);

const final = db.prepare('PRAGMA table_info(requests)').all().map(c => c.name);
const count = db.prepare('SELECT count(*) as c FROM requests').get();
console.log('✓ Columns:', final.join(', '));
console.log('✓ Rows in requests:', count.c);
console.log('Migration complete.');
