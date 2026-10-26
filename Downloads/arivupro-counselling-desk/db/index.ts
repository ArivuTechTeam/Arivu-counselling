import * as schema from "./schema";

// On Railway (Node.js), use better-sqlite3. On Cloudflare Workers, use D1.
export function getDb() {
  if (process.env.RAILWAY === "true" || process.env.NODE_ENV === "test") {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Database = require("better-sqlite3");
    const { drizzle } = require("drizzle-orm/better-sqlite3");
    const dbPath = process.env.DATABASE_PATH || "/data/counselling.db";
    const sqlite = new Database(dbPath);
    sqlite.pragma("journal_mode = WAL");
    return drizzle(sqlite, { schema });
  }

  // Cloudflare Workers path
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { env } = require("cloudflare:workers");
  const { drizzle } = require("drizzle-orm/d1");
  if (!env.DB) {
    throw new Error(
      "Cloudflare D1 binding `DB` is unavailable."
    );
  }
  return drizzle(env.DB, { schema });
}
