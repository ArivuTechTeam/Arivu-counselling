import * as schema from "./schema";
import { drizzle as drizzleBetter } from "drizzle-orm/better-sqlite3";
import BetterSqlite3 from "better-sqlite3";

let _db: ReturnType<typeof drizzleBetter> | null = null;

export function getDb() {
  if (process.env.RAILWAY === "true") {
    if (!_db) {
      const dbPath = process.env.DATABASE_PATH || "/data/counselling.db";
      const sqlite = new BetterSqlite3(dbPath);
      sqlite.pragma("journal_mode = WAL");
      _db = drizzleBetter(sqlite, { schema });
    }
    return _db;
  }

  // Cloudflare Workers — dynamic require at runtime only
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { env } = require("cloudflare:workers");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { drizzle } = require("drizzle-orm/d1");
  if (!env.DB) throw new Error("Cloudflare D1 binding `DB` is unavailable.");
  return drizzle(env.DB, { schema });
}
