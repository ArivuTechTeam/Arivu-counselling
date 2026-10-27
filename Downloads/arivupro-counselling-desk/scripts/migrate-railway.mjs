// Runs at Railway container startup before the Next.js server starts.
// Creates all required tables in the SQLite file at DATABASE_PATH.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
const rawPath = process.env.DATABASE_PATH || "/data/counselling.db";
const dbPath = rawPath.startsWith("/data/") ? rawPath : "/data/counselling.db";

mkdirSync(dirname(dbPath), { recursive: true });

const Database = require("better-sqlite3");
const db = new Database(dbPath);
db.pragma("journal_mode = WAL");

db.exec(`
CREATE TABLE IF NOT EXISTS requests (
  id text PRIMARY KEY NOT NULL,
  user_id text NOT NULL,
  name text NOT NULL,
  email text NOT NULL,
  phone text NOT NULL,
  course text NOT NULL,
  level text NOT NULL,
  slot text NOT NULL DEFAULT '',
  concern text NOT NULL,
  status text NOT NULL DEFAULT 'Requested',
  notes text NOT NULL DEFAULT '',
  meet_link text NOT NULL DEFAULT '',
  otp_verified integer NOT NULL DEFAULT 0,
  email_sent integer NOT NULL DEFAULT 0,
  created text NOT NULL
);

CREATE TABLE IF NOT EXISTS staff_owner (
  id text PRIMARY KEY NOT NULL,
  user_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_store (
  phone text PRIMARY KEY NOT NULL,
  code text NOT NULL,
  expires_at text NOT NULL,
  attempts integer NOT NULL DEFAULT 0
);
`);

// Add columns if they were missing from an older schema
const cols = db.prepare("PRAGMA table_info(requests)").all().map(c => c.name);
if (!cols.includes("meet_link"))    db.exec("ALTER TABLE requests ADD COLUMN meet_link text NOT NULL DEFAULT ''");
if (!cols.includes("otp_verified")) db.exec("ALTER TABLE requests ADD COLUMN otp_verified integer NOT NULL DEFAULT 0");
if (!cols.includes("email_sent"))   db.exec("ALTER TABLE requests ADD COLUMN email_sent integer NOT NULL DEFAULT 0");
if (!cols.includes("slot"))         db.exec("ALTER TABLE requests ADD COLUMN slot text NOT NULL DEFAULT ''");

const count = db.prepare("SELECT count(*) as c FROM requests").get();
console.log(`✓ DB ready at ${dbPath} — ${count.c} existing requests`);
db.close();
