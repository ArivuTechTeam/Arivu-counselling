export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const dbPath = (() => {
    const raw = process.env.DATABASE_PATH || '/data/counselling.db';
    return raw.startsWith('/data/') ? raw : '/data/counselling.db';
  })();

  let dbInfo: Record<string, unknown> = { path: dbPath };
  let rows: unknown[] = [];

  try {
    const { createRequire } = await import('node:module');
    const require = createRequire(import.meta.url);
    const Database = require('better-sqlite3');
    const db = new Database(dbPath);
    const count = db.prepare('SELECT count(*) as c FROM requests').get() as { c: number };
    const recent = db.prepare('SELECT id, name, email, course, status, created FROM requests ORDER BY created DESC LIMIT 5').all();
    dbInfo = { path: dbPath, rowCount: count.c };
    rows = recent;
    db.close();
  } catch (e: unknown) {
    dbInfo = { path: dbPath, error: e instanceof Error ? e.message : String(e) };
  }

  return Response.json({
    env: {
      RAILWAY: process.env.RAILWAY,
      DATABASE_PATH: process.env.DATABASE_PATH,
      NODE_ENV: process.env.NODE_ENV,
      resolvedDbPath: dbPath,
    },
    origin: req.headers.get('origin'),
    host: req.headers.get('host'),
    reqUrl: req.url,
    db: dbInfo,
    recentRows: rows,
  });
}

// POST /api/debug — insert a test row directly, bypassing all auth/validation
export async function POST(req: Request) {
  const dbPath = (() => {
    const raw = process.env.DATABASE_PATH || '/data/counselling.db';
    return raw.startsWith('/data/') ? raw : '/data/counselling.db';
  })();

  try {
    const { createRequire } = await import('node:module');
    const require = createRequire(import.meta.url);
    const Database = require('better-sqlite3');
    const db = new Database(dbPath);
    const id = `debug-${Date.now()}`;
    db.prepare(`INSERT INTO requests (id,user_id,name,email,phone,course,level,slot,concern,status,notes,meet_link,otp_verified,email_sent,created)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
    ).run(id, 'debug', 'Debug Test', 'debug@test.com', '9999999999', 'CA', 'Foundation', '', 'Debug test row', 'Requested', '', '', 0, 0, new Date().toISOString());
    const count = db.prepare('SELECT count(*) as c FROM requests').get() as { c: number };
    db.close();
    return Response.json({ ok: true, insertedId: id, totalRows: count.c });
  } catch (e: unknown) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }
}
